"""Validate a Docker-save OCI archive by content, not tag/config-name guesses."""
import hashlib
import json
from pathlib import PurePosixPath
import re
import tarfile


def validate_image_archive(stream, expected_digest, platform, diff_ids):
    files, documents = {}, {}
    with tarfile.open(fileobj=stream, mode='r|*') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or '\\' in member.name:
                raise ValueError('Unsafe archive path')
            if member.isdir():
                continue
            if not member.isfile() or str(path) in files:
                raise ValueError('Unsupported link or duplicate archive member')
            name = str(path)
            data = archive.extractfile(member)
            value = hashlib.sha256()
            small = bytearray() if member.size <= 4 * 1024 * 1024 else None
            for block in iter(lambda: data.read(1024 * 1024), b''):
                value.update(block)
                if small is not None:
                    small.extend(block)
            files[name] = (value.hexdigest(), member.size)
            if name.startswith('blobs/'):
                if not re.fullmatch(r'blobs/sha256/[a-f0-9]{64}', name) or value.hexdigest() != path.name:
                    raise ValueError('Blob content digest mismatch')
            if small is not None:
                try:
                    documents[name] = json.loads(small)
                except (ValueError, UnicodeError):
                    pass

    if documents.get('oci-layout', {}).get('imageLayoutVersion') != '1.0.0':
        raise ValueError('OCI layout missing or unsupported')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', expected_digest):
        raise ValueError('Invalid expected digest')

    def resolve(descriptor):
        digest = descriptor.get('digest', '')
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
            raise ValueError('Unsupported descriptor digest')
        name = 'blobs/sha256/' + digest.split(':')[1]
        if name not in files or files[name] != (digest.split(':')[1], descriptor.get('size')):
            raise ValueError('Referenced blob missing or wrong size')
        return name

    seen, configs = set(), []

    def walk(descriptor, expected_platform=None):
        name = resolve(descriptor)
        if name in seen:
            return
        seen.add(name)
        doc = documents.get(name, {})
        kind = descriptor.get('mediaType', '')
        if kind.endswith('image.index.v1+json') or kind.endswith('manifest.list.v2+json'):
            if not doc.get('manifests'):
                raise ValueError('Empty image index')
            for child in doc['manifests']:
                walk(child, child.get('platform'))
        elif kind.endswith('image.manifest.v1+json') or kind.endswith('manifest.v2+json'):
            config_name = resolve(doc.get('config', {}))
            config = documents.get(config_name)
            if not isinstance(config, dict) or not isinstance(doc.get('layers'), list):
                raise ValueError('Missing image config or layers')
            if not config and doc['config'].get('mediaType') != 'application/vnd.oci.empty.v1+json':
                raise ValueError('Unexpected empty image config')
            for layer in doc['layers']:
                resolve(layer)
            configs.append((config_name, config, expected_platform, doc['layers']))
        else:
            raise ValueError('Unsupported index/manifest media type')

    roots = documents.get('index.json', {}).get('manifests', [])
    for root in roots:
        walk(root, root.get('platform'))
    root_path = 'blobs/sha256/' + expected_digest.split(':')[1]
    if root_path not in seen:
        raise ValueError('Expected image digest is not reachable from archive index')
    # Select configs reachable specifically from the expected image descriptor.
    seen.clear(); configs.clear()
    expected = next((x for x in roots if x['digest'] == expected_digest), None)
    if expected is None:
        doc = documents.get(root_path, {})
        expected = dict(digest=expected_digest, size=files[root_path][1], mediaType=doc.get('mediaType'))
    walk(expected)
    selected = [(name, config, layers) for name, config, _, layers in configs
                if (config.get('os'), config.get('architecture')) == tuple(platform)
                and config.get('rootfs', {}).get('diff_ids') == diff_ids]
    if not selected:
        raise ValueError('Expected platform/config rootfs not found')
    # Docker compatibility manifest must reference real configs and layers too.
    legacy = documents.get('manifest.json')
    if not isinstance(legacy, list) or not legacy:
        raise ValueError('Docker compatibility manifest missing')
    for item in legacy:
        if item.get('Config') not in files or any(x not in files for x in item.get('Layers', [])):
            raise ValueError('Docker compatibility manifest references missing content')
    if not any(item['Config'] in {x[0] for x in selected} for item in legacy):
        raise ValueError('Docker and OCI image identities disagree')
    return dict(format='OCI layout + Docker manifest', expected_image_digest=expected_digest,
                files=len(files), blobs=sum(x.startswith('blobs/') for x in files),
                matching_configs=len(selected), referenced_layers=len(selected[0][2]),
                content_digests_and_references_verified=True)
