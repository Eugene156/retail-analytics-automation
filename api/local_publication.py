"""Windows/NTFS exact-byte file adapter. No DB grant, worker, route or approval.

The configured root is server-owned. Authorization must be supplied by a later
transactional outbox adapter; this module is NOT an approval credential.
"""
import ctypes
from ctypes import wintypes as w
from contextlib import ExitStack, contextmanager
from hashlib import sha256
import os
from pathlib import Path
import re
from uuid import UUID, uuid4


class PublicationError(RuntimeError):
    pass


class UnsafeTarget(PublicationError):
    pass


class TargetConflict(PublicationError):
    pass


class PublicationBusy(PublicationError):
    pass


class AuthorizationDenied(PublicationError):
    pass


class PublicationUnknown(PublicationError):
    """Reconcile before retrying; a successful rename may already exist."""


class _MissingTarget(PublicationError):
    pass


class _Info(ctypes.Structure):
    _fields_=[('attributes',w.DWORD),('creation',w.FILETIME),('access',w.FILETIME),('write',w.FILETIME),
              ('volume',w.DWORD),('size_high',w.DWORD),('size_low',w.DWORD),('links',w.DWORD),
              ('index_high',w.DWORD),('index_low',w.DWORD)]


class _Rename(ctypes.Structure):
    _fields_=[('replace',w.DWORD),('root',w.HANDLE),('length',w.DWORD),('name',w.WCHAR*1)]


class _Disposition(ctypes.Structure):
    _fields_=[('delete',w.BOOLEAN)]


class WindowsPublicationFiles:
    """Fixed reports/approved/v1/{canonical UUID}/revision-1.json target only.

    Reject every reparse ancestor, stream, UNC path, non-NTFS volume and file
    hardlink. Directory handles deny rename/delete while validation/write runs.
    Renaming the still-open exclusive staged file never replaces a target.
    Trusted local ACLs are still required: this is not a hostile-admin sandbox.
    """
    def __init__(self, root):
        if os.name!='nt':
            raise UnsafeTarget('Windows NTFS adapter required')
        root=Path(root)
        if not root.is_absolute() or len(root.parts)<3 or not re.fullmatch(r'[A-Za-z]:',root.drive):
            raise UnsafeTarget('Explicit local workspace root required')
        if any(p in ('.','..') or ':' in p or p.endswith((' ','.')) for p in root.parts[1:]):
            raise UnsafeTarget('Invalid workspace root')
        self.root=root
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        signatures={
            'CreateFileW':([w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE],w.HANDLE),
            'CloseHandle':([w.HANDLE],w.BOOL),
            'GetFileInformationByHandle':([w.HANDLE,ctypes.POINTER(_Info)],w.BOOL),
            'GetFinalPathNameByHandleW':([w.HANDLE,w.LPWSTR,w.DWORD,w.DWORD],w.DWORD),
            'CreateDirectoryW':([w.LPCWSTR,w.LPVOID],w.BOOL),
            'WriteFile':([w.HANDLE,w.LPCVOID,w.DWORD,ctypes.POINTER(w.DWORD),w.LPVOID],w.BOOL),
            'ReadFile':([w.HANDLE,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD),w.LPVOID],w.BOOL),
            'FlushFileBuffers':([w.HANDLE],w.BOOL),
            'SetFileInformationByHandle':([w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD],w.BOOL),
            'GetVolumeInformationW':([w.LPCWSTR,w.LPWSTR,w.DWORD,ctypes.POINTER(w.DWORD),
                ctypes.POINTER(w.DWORD),ctypes.POINTER(w.DWORD),w.LPWSTR,w.DWORD],w.BOOL),
        }
        for name,(args,result) in signatures.items():
            fn=getattr(self.api,name); fn.argtypes=args; fn.restype=result
        fs=ctypes.create_unicode_buffer(32)
        if not self.api.GetVolumeInformationW(root.anchor,None,0,None,None,None,fs,len(fs)) or fs.value!='NTFS':
            raise UnsafeTarget('Local NTFS volume required')

    def _error(self):
        code=ctypes.get_last_error()
        if code in (2,3):
            raise _MissingTarget('Fixed target does not exist')
        if code in (32,33):
            raise PublicationBusy('Publication path is busy')
        # Numeric diagnostics only: never expose paths, payloads or credentials.
        raise UnsafeTarget(f'Filesystem operation denied (Win32 {code})')

    @contextmanager
    def _open(self,path,write=False,directory=False):
        # Directory READ_ATTRIBUTES; files either GENERIC_READ or private
        # GENERIC_READ|WRITE|DELETE. No FILE_SHARE_DELETE anywhere.
        access=0x80 if directory else (0xC0010000 if write else 0x80000000)
        handle=self.api.CreateFileW(str(path),access,3 if directory else (0 if write else 1),None,
            1 if write else 3,0x00200000|(0x02000000 if directory else 0),None)
        if handle==w.HANDLE(-1).value:
            self._error()
        try:
            info=_Info()
            if not self.api.GetFileInformationByHandle(handle,ctypes.byref(info)):
                self._error()
            if info.attributes&0x400 or bool(info.attributes&0x10)!=directory or (not directory and info.links!=1):
                raise UnsafeTarget('Reparse point or aliased target denied')
            if not self._handle_path_matches(handle,path):
                raise UnsafeTarget('Handle path does not match fixed target')
            yield handle,info
        finally:
            self.api.CloseHandle(handle)

    def _handle_path_matches(self,handle,path):
        buf=ctypes.create_unicode_buffer(32768)
        count=self.api.GetFinalPathNameByHandleW(handle,buf,len(buf),0)
        expected=os.path.normcase(os.path.normpath(str(path)))
        prefix=chr(92)*2+'?'+chr(92)
        actual=os.path.normcase(os.path.normpath(buf.value.removeprefix(prefix)))
        return bool(count and count<len(buf) and actual==expected)

    def _case(self,case_id):
        try:
            case=UUID(str(case_id))
        except (ValueError,AttributeError):
            raise UnsafeTarget('Canonical case UUID required') from None
        if str(case)!=str(case_id):
            raise UnsafeTarget('Canonical case UUID required')
        return str(case)

    @contextmanager
    def _parents(self,case,create=False):
        with ExitStack() as stack:
            path=Path(self.root.anchor)
            stack.enter_context(self._open(path,directory=True))
            for part in (*self.root.parts[1:],'reports','approved','v1',case):
                path=path/part
                if create and path.is_relative_to(self.root) and path!=self.root:
                    if not self.api.CreateDirectoryW(str(path),None) and ctypes.get_last_error()!=183:
                        self._error()
                try:
                    stack.enter_context(self._open(path,directory=True))
                except _MissingTarget:
                    if not create:
                        yield None
                        return
                    raise
            yield path

    def _binding(self,content,expected_hash):
        if not isinstance(content,bytes) or not 1<=len(content)<=131072 or not isinstance(expected_hash,str) \
                or not re.fullmatch(r'[a-f0-9]{64}',expected_hash) or sha256(content).hexdigest()!=expected_hash:
            raise TargetConflict('Exact content binding required')

    def _inspect(self,parent,content,expected_hash):
        target=parent/'revision-1.json'
        try:
            with self._open(target) as (handle,info):
                if (info.size_high<<32)+info.size_low!=len(content):
                    raise TargetConflict('Existing target differs; never overwrite')
                buf=ctypes.create_string_buffer(len(content)+1); read=w.DWORD()
                if not self.api.ReadFile(handle,buf,len(buf),ctypes.byref(read),None):
                    self._error()
                value=buf.raw[:read.value]
                if value!=content or sha256(value).hexdigest()!=expected_hash:
                    raise TargetConflict('Existing target differs; never overwrite')
                return 'matching'
        except _MissingTarget:
            return 'missing'

    def reconcile(self,case_id,content,expected_hash):
        """Read-only observation, not authorization or a database receipt."""
        self._binding(content,expected_hash)
        with self._parents(self._case(case_id)) as parent:
            return 'missing' if parent is None else self._inspect(parent,content,expected_hash)

    def publish(self,case_id,content,expected_hash,authorize,checkpoint=None):
        self._binding(content,expected_hash)
        case=self._case(case_id)
        if not callable(authorize) or authorize() is not True:
            raise AuthorizationDenied('Fresh authorization required')
        with self._parents(case,create=True) as parent:
            if self._inspect(parent,content,expected_hash)=='matching':
                return 'reconciled'
            staged=parent/('.staged-'+uuid4().hex+'.tmp')
            renamed=False
            with self._open(staged,write=True) as (handle,_):
                try:
                    written=w.DWORD()
                    if not self.api.WriteFile(handle,content,len(content),ctypes.byref(written),None) or written.value!=len(content):
                        raise PublicationUnknown('Stage write failed; reconcile before retry')
                    if not self.api.FlushFileBuffers(handle):
                        raise PublicationUnknown('Stage flush failed; reconcile before retry')
                    if checkpoint: checkpoint('staged')
                    if authorize() is not True:
                        raise AuthorizationDenied('Authorization expired or revoked before install')
                    target=parent/'revision-1.json'
                    name=str(target).encode('utf-16-le')
                    # FileName is NUL-terminated; FileNameLength counts only
                    # pathname bytes, not the terminating UTF-16 code unit.
                    buffer=ctypes.create_string_buffer(_Rename.name.offset+len(name)+2)
                    info=ctypes.cast(buffer,ctypes.POINTER(_Rename)).contents
                    info.replace=0; info.root=None; info.length=len(name)
                    ctypes.memmove(ctypes.addressof(buffer)+_Rename.name.offset,name,len(name))
                    if not self.api.SetFileInformationByHandle(handle,3,buffer,len(buffer)):
                        # Rename failure is never permission to overwrite or blindly retry.
                        raise PublicationUnknown('Install outcome needs reconciliation')
                    renamed=True
                    # A successful Win32 return is not proof of the destination.
                    # Keep any renamed file for reconciliation, never delete it.
                    if not self._handle_path_matches(handle,target):
                        raise PublicationUnknown('Installed handle needs reconciliation')
                    if checkpoint: checkpoint('installed')
                    if not self.api.FlushFileBuffers(handle):
                        raise PublicationUnknown('Installed file needs reconciliation')
                finally:
                    if not renamed:
                        # Delete only our still-open staged handle, never a pathname
                        # that could have been swapped. Process crashes retain stages.
                        disposition=_Disposition(True)
                        self.api.SetFileInformationByHandle(handle,4,ctypes.byref(disposition),ctypes.sizeof(disposition))
            # Close the exclusive handle before reopening the exact final path.
            # Ancestors remain locked; never report success for a missing file.
            try:
                observed=self._inspect(parent,content,expected_hash)
            except PublicationError:
                raise PublicationUnknown('Installed target needs reconciliation') from None
            if observed!='matching':
                raise PublicationUnknown('Installed target needs reconciliation')
            return 'created'
