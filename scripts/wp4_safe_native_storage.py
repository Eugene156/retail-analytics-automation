"""Private Windows capture storage: protected DACL, locked paths, DPAPI frames.

No operational credentials generated. No publication adapter or subprocess.
All platform errors are finite; plaintext never reaches a filesystem path.
"""
import ctypes as c
from ctypes import wintypes as w
from contextlib import ExitStack
from hashlib import sha256
import os
from pathlib import Path
import struct


class StorageDenied(Exception):
    def __init__(self):super().__init__('N1 private storage denied')


def require(value):
    if not value:raise StorageDenied()


class Blob(c.Structure):_fields_=[('size',w.DWORD),('data',c.POINTER(c.c_ubyte))]
class Security(c.Structure):_fields_=[('size',w.DWORD),('descriptor',c.c_void_p),('inherit',w.BOOL)]
class Info(c.Structure):
    _fields_=[('attrs',w.DWORD),('created',w.FILETIME),('accessed',w.FILETIME),('written',w.FILETIME),
             ('volume',w.DWORD),('size_hi',w.DWORD),('size_lo',w.DWORD),('links',w.DWORD),('id_hi',w.DWORD),('id_lo',w.DWORD)]


class Windows:
    def __init__(self):
        require(os.name=='nt')
        self.k=c.WinDLL('kernel32',use_last_error=True);self.a=c.WinDLL('advapi32',use_last_error=True)
        self.crypto=c.WinDLL('crypt32',use_last_error=True)
        signatures=[(self.k,'CreateFileW',w.HANDLE,[w.LPCWSTR,w.DWORD,w.DWORD,c.POINTER(Security),w.DWORD,w.DWORD,w.HANDLE]),
            (self.k,'CreateDirectoryW',w.BOOL,[w.LPCWSTR,c.POINTER(Security)]),
            (self.k,'CloseHandle',w.BOOL,[w.HANDLE]),(self.k,'GetCurrentProcess',w.HANDLE,[]),
            (self.k,'GetFileInformationByHandle',w.BOOL,[w.HANDLE,c.POINTER(Info)]),
            (self.k,'GetFinalPathNameByHandleW',w.DWORD,[w.HANDLE,w.LPWSTR,w.DWORD,w.DWORD]),
            (self.k,'WriteFile',w.BOOL,[w.HANDLE,c.c_void_p,w.DWORD,c.POINTER(w.DWORD),c.c_void_p]),
            (self.k,'ReadFile',w.BOOL,[w.HANDLE,c.c_void_p,w.DWORD,c.POINTER(w.DWORD),c.c_void_p]),
            (self.k,'FlushFileBuffers',w.BOOL,[w.HANDLE]),(self.k,'LocalFree',c.c_void_p,[c.c_void_p]),
            (self.a,'OpenProcessToken',w.BOOL,[w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)]),
            (self.a,'GetTokenInformation',w.BOOL,[w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)]),
            (self.a,'ConvertSidToStringSidW',w.BOOL,[c.c_void_p,c.POINTER(w.LPWSTR)]),
            (self.a,'ConvertStringSecurityDescriptorToSecurityDescriptorW',w.BOOL,[w.LPCWSTR,w.DWORD,c.POINTER(c.c_void_p),c.POINTER(w.DWORD)]),
            (self.a,'GetSecurityInfo',w.DWORD,[w.HANDLE,c.c_int,w.DWORD,c.POINTER(c.c_void_p),c.c_void_p,c.POINTER(c.c_void_p),c.c_void_p,c.POINTER(c.c_void_p)]),
            (self.a,'GetSecurityDescriptorControl',w.BOOL,[c.c_void_p,c.POINTER(w.WORD),c.POINTER(w.DWORD)]),
            (self.a,'GetAclInformation',w.BOOL,[c.c_void_p,c.c_void_p,w.DWORD,c.c_int]),
            (self.a,'GetAce',w.BOOL,[c.c_void_p,w.DWORD,c.POINTER(c.c_void_p)]),
            (self.crypto,'CryptProtectData',w.BOOL,[c.POINTER(Blob),w.LPCWSTR,c.POINTER(Blob),c.c_void_p,c.c_void_p,w.DWORD,c.POINTER(Blob)]),
            (self.crypto,'CryptUnprotectData',w.BOOL,[c.POINTER(Blob),c.c_void_p,c.POINTER(Blob),c.c_void_p,c.c_void_p,w.DWORD,c.POINTER(Blob)])]
        for lib,name,result,args in signatures:
            func=getattr(lib,name);func.restype=result;func.argtypes=args
        token=w.HANDLE();require(self.a.OpenProcessToken(self.k.GetCurrentProcess(),8,c.byref(token)))
        try:
            size=w.DWORD();self.a.GetTokenInformation(token,1,None,0,c.byref(size))
            data=c.create_string_buffer(size.value);require(self.a.GetTokenInformation(token,1,data,size,c.byref(size)))
            self.sid=self.sid_text(c.cast(data,c.POINTER(c.c_void_p))[0])
        finally:self.k.CloseHandle(token)
        descriptor=c.c_void_p()
        require(self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW('O:'+self.sid+'D:P(A;;FA;;;'+self.sid+')(A;;FA;;;SY)',1,c.byref(descriptor),None))
        self.descriptor=descriptor;self.security=Security(c.sizeof(Security),descriptor,False)

    def sid_text(self,sid):
        text=w.LPWSTR();require(self.a.ConvertSidToStringSidW(sid,c.byref(text)))
        try:return text.value
        finally:self.k.LocalFree(c.cast(text,c.c_void_p))

    def close(self):
        if self.descriptor:self.k.LocalFree(self.descriptor);self.descriptor=None

    def acl(self,handle):
        owner=c.c_void_p();acl=c.c_void_p();descriptor=c.c_void_p()
        require(self.a.GetSecurityInfo(handle,1,5,c.byref(owner),None,c.byref(acl),None,c.byref(descriptor))==0)
        try:
            require(self.sid_text(owner)==self.sid)
            control=w.WORD();revision=w.DWORD();require(self.a.GetSecurityDescriptorControl(descriptor,c.byref(control),c.byref(revision)))
            require(control.value&0x1000 and acl.value)
            info=(w.DWORD*3)();require(self.a.GetAclInformation(acl,info,c.sizeof(info),2));require(info[0]==2)
            identities=set()
            for index in range(2):
                ace=c.c_void_p();require(self.a.GetAce(acl,index,c.byref(ace)))
                header=c.string_at(ace,8);require(header[0]==0 and header[1]==0 and struct.unpack('<I',header[4:8])[0]==0x1f01ff)
                identities.add(self.sid_text(ace.value+8))
            require(identities=={self.sid,'S-1-5-18'})
        finally:self.k.LocalFree(descriptor)

    def open(self,path,*,directory=False,new=False,private=False):
        access=0x20080 if directory else (0xc0000000|0x20000 if new else 0x80020000)
        handle=self.k.CreateFileW(str(path),access,3 if directory else 0,c.byref(self.security) if new else None,
            1 if new else 3,0x200000|(0x2000000 if directory else 0),None)
        require(handle not in (None,c.c_void_p(-1).value))
        try:
            info=Info();require(self.k.GetFileInformationByHandle(handle,c.byref(info)))
            require(not info.attrs&0x400 and bool(info.attrs&0x10)==directory and (directory or info.links==1))
            # Normalized handle identity remains mandatory. An opened-name
            # alternative failed the same sandbox observation and is not used.
            buffer=c.create_unicode_buffer(32768);count=self.k.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0)
            require(0<count<len(buffer))
            actual=buffer.value.removeprefix('\\\\?\\')
            require(os.path.normcase(os.path.normpath(actual))==os.path.normcase(str(path.resolve(strict=True))))
            if private:self.acl(handle)
            return handle
        except Exception:self.k.CloseHandle(handle);raise StorageDenied() from None

    def crypt(self,data,entropy,*,decrypt=False):
        source=c.create_string_buffer(data);extra=c.create_string_buffer(entropy)
        a=Blob(len(data),c.cast(source,c.POINTER(c.c_ubyte)));b=Blob(len(entropy),c.cast(extra,c.POINTER(c.c_ubyte)));out=Blob()
        fn=self.crypto.CryptUnprotectData if decrypt else self.crypto.CryptProtectData
        require(fn(c.byref(a),None,c.byref(b),None,None,1,c.byref(out)))
        try:return c.string_at(out.data,out.size)
        finally:self.k.LocalFree(c.cast(out.data,c.c_void_p))

    def write(self,handle,data):
        done=w.DWORD();require(self.k.WriteFile(handle,data,len(data),c.byref(done),None) and done.value==len(data))
    def read(self,handle,size):
        buffer=c.create_string_buffer(size);done=w.DWORD();require(self.k.ReadFile(handle,buffer,size,c.byref(done),None))
        return buffer.raw[:done.value]


class PrivateStore:
    """Fresh fixed run directory, owner+SYSTEM ACL, encrypted immutable captures."""
    NAMES=('source-archive','reference-archive','source-before','source-after','reference-before','reference-after','native-manifest')
    def __init__(self,base,run_id,binding):
        import wp4_safe_fixture_contract as i1
        i1.identity(run_id);require(type(binding) is bytes and len(binding)==32)
        root=Path(__file__).resolve().parents[1]/'.local/wp4-safe-native-private'
        require(isinstance(base,Path) and base==root and base.is_dir())
        self._api=Windows();self._stack=ExitStack();self._binding=binding;self._run_id=run_id;self._closed=False;self._written=set()
        try:
            # Hold ancestors without FILE_SHARE_DELETE through the whole lifetime.
            for parent in reversed((base,*base.parents)):
                handle=self._api.open(parent,directory=True);self._stack.callback(self._api.k.CloseHandle,handle)
            self.path=base/run_id;require(not self.path.exists())
            require(self._api.k.CreateDirectoryW(str(self.path),c.byref(self._api.security)))
            handle=self._api.open(self.path,directory=True,private=True);self._stack.callback(self._api.k.CloseHandle,handle)
        except Exception:self.close();raise StorageDenied() from None
    def __repr__(self):return '<PrivateStore: encrypted, redacted>'
    def __reduce_ex__(self,protocol):raise StorageDenied()
    def check(self,run_id,binding):require(not self._closed and self._run_id==run_id and self._binding==binding)
    def _entropy(self,name,index):return sha256(self._binding+name.encode()+struct.pack('<Q',index)).digest()
    def put(self,name,chunks):
        require(not self._closed and name in self.NAMES and name not in self._written)
        handle=None
        try:
            handle=self._api.open(self.path/(name+'.dpapi'),new=True,private=True);h=sha256();size=0;index=0
            self._api.write(handle,b'N1DPAPI1')
            for chunk in chunks:
                require(type(chunk) is bytes and 0<len(chunk)<=1048576 and size+len(chunk)<=536870912)
                frame=self._api.crypt(b'D'+chunk,self._entropy(name,index));self._api.write(handle,struct.pack('<I',len(frame))+frame)
                h.update(chunk);size+=len(chunk);index+=1
            footer=self._api.crypt(b'F'+struct.pack('<QQ',index,size)+h.digest(),self._entropy(name,index))
            self._api.write(handle,struct.pack('<I',len(footer))+footer);require(self._api.k.FlushFileBuffers(handle))
            self._written.add(name);return dict(bytes=size,sha256=h.hexdigest())
        except Exception:self._closed=True;raise StorageDenied() from None
        finally:
            if handle is not None:self._api.k.CloseHandle(handle)
    def read(self,name):
        require(not self._closed and name in self.NAMES)
        handle=self._api.open(self.path/(name+'.dpapi'),private=True)
        try:
            require(self._api.read(handle,8)==b'N1DPAPI1');data=bytearray();index=0
            while True:
                header=self._api.read(handle,4);require(len(header)==4)
                size=struct.unpack('<I',header)[0];require(0<size<=1048576+4096)
                frame=self._api.read(handle,size);require(len(frame)==size)
                raw=self._api.crypt(frame,self._entropy(name,index),decrypt=True)
                if raw[:1]==b'F':
                    require(raw==b'F'+struct.pack('<QQ',index,len(data))+sha256(data).digest())
                    require(not self._api.read(handle,1));return bytes(data)
                require(raw[:1]==b'D' and len(data)+len(raw)-1<=536870912);data.extend(raw[1:]);index+=1
        except Exception:raise StorageDenied() from None
        finally:self._api.k.CloseHandle(handle)
    def close(self):
        self._closed=True
        if hasattr(self,'_stack'):self._stack.close()
        if hasattr(self,'_api'):self._api.close()
