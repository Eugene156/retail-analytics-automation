import hashlib
import io
import json
import tarfile

import unittest

from scripts.docker_archive import validate_image_archive


def fixture(change=None, attestation=False):
    entries = {}
    def blob(data, kind):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        digest = hashlib.sha256(raw).hexdigest()
        entries['blobs/sha256/' + digest] = raw
        return dict(digest='sha256:' + digest, size=len(raw), mediaType=kind)
    layer = blob(b'synthetic layer', 'application/vnd.oci.image.layer.v1.tar')
    diff_ids = [layer['digest']]
    config = blob(dict(os='linux', architecture='amd64', rootfs=dict(type='layers', diff_ids=diff_ids)), 'application/vnd.oci.image.config.v1+json')
    manifest = blob(dict(schemaVersion=2, config=config, layers=[layer]), 'application/vnd.oci.image.manifest.v1+json')
    manifests = [manifest]
    if attestation:
        empty = blob(b'{}', 'application/vnd.oci.empty.v1+json')
        statement = blob(b'{"synthetic":"attestation"}', 'application/vnd.in-toto+json')
        manifests.append(blob(dict(schemaVersion=2,config=empty,layers=[statement]), 'application/vnd.oci.image.manifest.v1+json'))
    root = blob(dict(schemaVersion=2, mediaType='application/vnd.oci.image.index.v1+json', manifests=manifests), 'application/vnd.oci.image.index.v1+json')
    entries['index.json'] = json.dumps(dict(schemaVersion=2, manifests=[root])).encode()
    entries['oci-layout'] = b'{"imageLayoutVersion":"1.0.0"}'
    entries['manifest.json'] = json.dumps([dict(Config='blobs/sha256/'+config['digest'].split(':')[1], Layers=['blobs/sha256/'+layer['digest'].split(':')[1]], RepoTags=[])]).encode()
    if change:
        change(entries, root, config, layer)
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as archive:
        for name, raw in entries.items():
            member = tarfile.TarInfo(name); member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    out.seek(0)
    return out, root['digest'], diff_ids


class DockerArchiveTests(unittest.TestCase):
    def test_index_id_is_not_config_id(self):
        stream, expected, diff_ids = fixture()
        result = validate_image_archive(stream, expected, ('linux','amd64'), diff_ids)
        self.assertTrue(result['content_digests_and_references_verified'])
        self.assertEqual(result['referenced_layers'], 1)

    def reject(self, corrupt):
        def change(entries, root, config, layer):
            if corrupt == 'missing_layer': del entries['blobs/sha256/'+layer['digest'].split(':')[1]]
            if corrupt == 'modified_blob': entries['blobs/sha256/'+layer['digest'].split(':')[1]] = b'changed'
            if corrupt == 'wrong_size':
                entries['index.json'] = json.dumps(dict(manifests=[dict(root,size=root['size']+1)])).encode()
            if corrupt == 'unsafe_path': entries['../unsafe'] = b'no'
        stream, expected, diff_ids = fixture(change)
        if corrupt == 'wrong_image': expected = 'sha256:'+'0'*64
        with self.assertRaises(ValueError):
            validate_image_archive(stream, expected, ('linux','arm64') if corrupt=='wrong_platform' else ('linux','amd64'),
                                   ['sha256:'+'0'*64] if corrupt=='wrong_rootfs' else diff_ids)

    def test_missing_layer(self): self.reject('missing_layer')
    def test_modified_blob(self): self.reject('modified_blob')
    def test_wrong_descriptor_size(self): self.reject('wrong_size')
    def test_wrong_image(self): self.reject('wrong_image')
    def test_wrong_platform(self): self.reject('wrong_platform')
    def test_wrong_rootfs(self): self.reject('wrong_rootfs')
    def test_unsafe_path(self): self.reject('unsafe_path')

    def test_valid_empty_config_for_attestation(self):
        stream, expected, diff_ids = fixture(attestation=True)
        result = validate_image_archive(stream, expected, ('linux','amd64'), diff_ids)
        self.assertTrue(result['content_digests_and_references_verified'])

    def test_missing_attestation_config_rejected(self):
        def change(entries, root, config, layer):
            del entries['blobs/sha256/'+hashlib.sha256(b'{}').hexdigest()]
        stream, expected, diff_ids = fixture(change, attestation=True)
        with self.assertRaises(ValueError):
            validate_image_archive(stream, expected, ('linux','amd64'), diff_ids)
