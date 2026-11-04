"""Pure contract and mocked handle checks; NOT native filesystem evidence."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes as w
from hashlib import sha256
import os
from pathlib import Path
import unittest
from unittest.mock import Mock
from uuid import uuid4
from api.local_publication import (WindowsPublicationFiles,UnsafeTarget,TargetConflict,
    PublicationBusy,AuthorizationDenied,PublicationUnknown,_MissingTarget,_Info,_Rename)

BODY=b'{"synthetic_test":true}'
HASH=sha256(BODY).hexdigest()


class PublicationContractTests(unittest.TestCase):
    def setUp(self):
        self.files=WindowsPublicationFiles.__new__(WindowsPublicationFiles)
        self.case=str(uuid4())

    def test_exact_binding(self):
        self.files._binding(BODY,HASH)

    def test_invalid_binding(self):
        for body,digest in ((BODY,'0'*64),(b'',HASH),(b'x'*131073,HASH),
                            (BODY.decode(),HASH),(BODY,HASH.upper()),(BODY,None)):
            with self.assertRaises(TargetConflict): self.files._binding(body,digest)

    def test_canonical_uuid(self):
        self.assertEqual(self.files._case(self.case),self.case)
        for case in ('../outside',self.case.upper(),self.case+':stream',None):
            with self.assertRaises(UnsafeTarget): self.files._case(case)

    def test_denied_authorization_never_opens_paths(self):
        self.files._parents=Mock(side_effect=AssertionError('Unexpected filesystem access'))
        for auth in (None,lambda:False,lambda:1,lambda:'yes'):
            with self.assertRaises(AuthorizationDenied):
                self.files.publish(self.case,BODY,HASH,auth)
        self.files._parents.assert_not_called()

    def test_missing_parent_reconciliation_does_not_publish(self):
        @contextmanager
        def parents(case):
            self.assertEqual(case,self.case)
            yield None
        self.files._parents=parents
        self.files.publish=Mock(side_effect=AssertionError('Unexpected publication'))
        self.assertEqual(self.files.reconcile(self.case,BODY,HASH),'missing')
        self.files.publish.assert_not_called()


@unittest.skipUnless(os.name=='nt','Windows ctypes error-state checks')
class MockedWindowsHandleTests(unittest.TestCase):
    def setUp(self):
        self.files=WindowsPublicationFiles.__new__(WindowsPublicationFiles)
        self.files.api=Mock()
        self.files.api.CreateFileW.return_value=71
        self.path=Path(r'C:\synthetic\root')
        def get_info(handle,pointer):
            info=ctypes.cast(pointer,ctypes.POINTER(_Info)).contents
            info.attributes=0x10; info.links=1
            return True
        self.files.api.GetFileInformationByHandle.side_effect=get_info
        def final_name(handle,buffer,size,flags):
            buffer.value=chr(92)*2+'?'+chr(92)+str(self.path)
            return len(buffer.value)
        self.files.api.GetFinalPathNameByHandleW.side_effect=final_name

    def test_windows_error_classification(self):
        for code,error in ((2,_MissingTarget),(3,_MissingTarget),(32,PublicationBusy),
                            (33,PublicationBusy),(5,UnsafeTarget)):
            ctypes.set_last_error(code)
            with self.assertRaises(error): self.files._error()

    def test_access_denial_not_missing_or_retryable(self):
        self.files.api.CreateFileW.return_value=w.HANDLE(-1).value
        ctypes.set_last_error(5)
        with self.assertRaisesRegex(UnsafeTarget,'Win32 5'):
            with self.files._open(self.path,directory=True): pass
        self.files.api.CloseHandle.assert_not_called()

    def test_extended_prefix_validated_and_handle_closed(self):
        with self.files._open(self.path,directory=True) as (handle,_):
            self.assertEqual(handle,71)
        self.files.api.CloseHandle.assert_called_once_with(71)
        args=self.files.api.CreateFileW.call_args.args
        self.assertEqual(args[1],0x80)
        self.assertEqual(args[2]&4,0)  # FILE_SHARE_DELETE must stay denied.
        self.assertEqual(args[5]&0x00200000,0x00200000)

    def test_reparse_handle_denied_and_closed(self):
        def reparse(handle,pointer):
            info=ctypes.cast(pointer,ctypes.POINTER(_Info)).contents
            info.attributes=0x410
            return True
        self.files.api.GetFileInformationByHandle.side_effect=reparse
        with self.assertRaisesRegex(UnsafeTarget,'Reparse point'):
            with self.files._open(self.path,directory=True): pass
        self.files.api.CloseHandle.assert_called_once_with(71)

    def test_changed_final_path_denied_and_closed(self):
        def changed(handle,buffer,size,flags):
            buffer.value=r'C:\synthetic\other'
            return len(buffer.value)
        self.files.api.GetFinalPathNameByHandleW.side_effect=changed
        with self.assertRaisesRegex(UnsafeTarget,'Handle path does not match'):
            with self.files._open(self.path,directory=True): pass
        self.files.api.CloseHandle.assert_called_once_with(71)

    def test_exception_after_open_closes_handle(self):
        with self.assertRaisesRegex(RuntimeError,'synthetic fault'):
            with self.files._open(self.path,directory=True):
                raise RuntimeError('synthetic fault')
        self.files.api.CloseHandle.assert_called_once_with(71)

    def test_unsafe_root_rejected_before_api_initialization(self):
        for root in ('C:/',r'C:\synthetic',r'\\server\share\root',
                     r'C:\synthetic\root:stream',r'C:\synthetic\root.',r'C:\synthetic\..\root'):
            with self.assertRaises(UnsafeTarget): WindowsPublicationFiles(root)


@unittest.skipUnless(os.name=='nt','Windows ctypes buffer checks')
class MockedPublicationInstallTests(unittest.TestCase):
    def setUp(self):
        self.files=WindowsPublicationFiles.__new__(WindowsPublicationFiles)
        self.files.api=Mock()
        self.case=str(uuid4())
        self.parent=Path(r'C:\synthetic\root')/'reports'/'approved'/'v1'/self.case
        self.target=self.parent/'revision-1.json'
        @contextmanager
        def parents(case,create=False):
            self.assertEqual(case,self.case)
            self.assertTrue(create)
            yield self.parent
        @contextmanager
        def opened(path,write=False):
            self.assertTrue(write)
            self.assertEqual(path.parent,self.parent)
            yield 71,_Info()
        self.files._parents=parents
        self.files._open=opened
        self.files._inspect=Mock(side_effect=['missing','matching'])
        self.files._handle_path_matches=Mock(return_value=True)
        def write(handle,body,length,pointer,overlapped):
            ctypes.cast(pointer,ctypes.POINTER(w.DWORD)).contents.value=length
            return True
        self.files.api.WriteFile.side_effect=write
        self.files.api.FlushFileBuffers.return_value=True
        self.files.api.SetFileInformationByHandle.return_value=True

    def test_rename_buffer_is_nul_terminated_without_length_including_nul(self):
        def install(handle,kind,buffer,length):
            if kind==3:
                info=ctypes.cast(buffer,ctypes.POINTER(_Rename)).contents
                name=str(self.target).encode('utf-16-le')
                self.assertEqual(info.replace,0)
                self.assertIsNone(info.root)
                self.assertEqual(info.length,len(name))
                self.assertEqual(length,_Rename.name.offset+len(name)+2)
                self.assertEqual(buffer.raw[_Rename.name.offset:],name+b'\0\0')
            return True
        self.files.api.SetFileInformationByHandle.side_effect=install
        self.assertEqual(self.files.publish(self.case,BODY,HASH,lambda:True),'created')

    def test_success_requires_exact_target_reopened_after_install(self):
        self.assertEqual(self.files.publish(self.case,BODY,HASH,lambda:True),'created')
        self.assertEqual(self.files._inspect.call_count,2)
        self.files._handle_path_matches.assert_called_once_with(71,self.target)

    def test_missing_target_after_reported_success_is_unknown_not_created(self):
        self.files._inspect.side_effect=['missing','missing']
        with self.assertRaises(PublicationUnknown):
            self.files.publish(self.case,BODY,HASH,lambda:True)
        self.assertEqual([call.args[1] for call in self.files.api.SetFileInformationByHandle.call_args_list],[3])

    def test_wrong_postrename_handle_path_is_unknown_and_never_deleted(self):
        self.files._handle_path_matches.return_value=False
        with self.assertRaises(PublicationUnknown):
            self.files.publish(self.case,BODY,HASH,lambda:True)
        self.assertEqual([call.args[1] for call in self.files.api.SetFileInformationByHandle.call_args_list],[3])

    def test_rename_failure_cleans_only_stage_and_never_reports_created(self):
        self.files.api.SetFileInformationByHandle.side_effect=[False,True]
        with self.assertRaises(PublicationUnknown):
            self.files.publish(self.case,BODY,HASH,lambda:True)
        self.assertEqual([call.args[1] for call in self.files.api.SetFileInformationByHandle.call_args_list],[3,4])
        self.files._handle_path_matches.assert_not_called()

    def test_second_authorization_denial_never_renames(self):
        values=iter([True,False])
        with self.assertRaises(AuthorizationDenied):
            self.files.publish(self.case,BODY,HASH,lambda:next(values))
        self.assertEqual([call.args[1] for call in self.files.api.SetFileInformationByHandle.call_args_list],[4])


if __name__=='__main__': unittest.main()
