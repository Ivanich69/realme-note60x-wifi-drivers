"""Read and check AVB boot files on the host; never opens a device."""

import hashlib
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def require(condition, message):
    if not condition:
        raise ValueError(message)


def region(data, offset, size):
    require(0 <= offset <= offset + size <= len(data), "AVB region out of bounds")
    return data[offset:offset + size]


def inspect_avb(raw):
    """Check payload hashes and, when present, the embedded-key RSA signature.

    Signature agreement with an embedded key does not establish device trust.
    Algorithm NONE has no authentication; its hashes still must be checked.
    The two supported metadata algorithms are NONE and SHA256_RSA4096.
    """
    require(len(raw) >= 64, "Image too small for footer")
    magic, major, minor, original, offset, size = struct.unpack_from(
        ">4sIIQQQ", raw, len(raw) - 64)
    require(magic == b"AVBf" and (major, minor) == (1, 0), "Unknown AVB footer")
    require(4096 <= original <= offset and offset + size <= len(raw) - 64,
            "Invalid AVB footer sizes")
    require(raw[-28:] == bytes(28), "Nonzero footer reserved bytes")
    meta = region(raw, offset, size)
    require(len(meta) >= 256 and meta[:4] == b"AVB0", "Missing VBMeta header")
    auth_size, aux_size = struct.unpack_from(">QQ", meta, 12)
    require(auth_size % 64 == aux_size % 64 == 0, "Unaligned VBMeta blocks")
    require(size == 256 + auth_size + aux_size, "Inconsistent VBMeta sizes")
    algorithm = struct.unpack_from(">I", meta, 28)[0]
    require(algorithm in (0, 2), "Unsupported metadata algorithm")
    auth = region(meta, 256, auth_size)
    aux = region(meta, 256 + auth_size, aux_size)
    hash_off, hash_size, sig_off, sig_size, key_off, key_size = (
        struct.unpack_from(">QQQQQQ", meta, 32))
    keymeta_off, keymeta_size, desc_off, desc_size = struct.unpack_from(">QQQQ", meta, 80)
    region(aux, keymeta_off, keymeta_size)
    descriptors = region(aux, desc_off, desc_size)
    flags = struct.unpack_from(">I", meta, 120)[0]
    hashes_found, properties, descriptor_tags = [], {}, []
    position = 0
    while position < len(descriptors):
        require(len(descriptors) - position >= 16, "Truncated AVB descriptor")
        tag, following = struct.unpack_from(">QQ", descriptors, position)
        require(following % 8 == 0, "Unaligned descriptor")
        entry = region(descriptors, position, 16 + following)
        descriptor_tags.append(tag)
        if tag == 2:
            require(len(entry) >= 132, "Truncated hash descriptor")
            image_size = struct.unpack_from(">Q", entry, 16)[0]
            hash_alg = entry[24:56].split(b"\0", 1)[0].decode("ascii")
            name_size, salt_size, digest_size, hash_flags = struct.unpack_from(">IIII", entry, 56)
            require(entry[72:132] == bytes(60), "Nonzero hash reserved bytes")
            variable = region(entry, 132, name_size + salt_size + digest_size)
            name = variable[:name_size].decode("utf-8")
            salt = variable[name_size:name_size + salt_size]
            digest = variable[name_size + salt_size:]
            require(image_size == original, "Hash range differs from original image size")
            hasher = hashlib.new(hash_alg)
            require(digest_size == hasher.digest_size, "Invalid digest length")
            hasher.update(salt)
            hasher.update(memoryview(raw)[:image_size])
            actual = hasher.digest()
            hashes_found.append({
                "partition_name": name, "image_bytes": image_size,
                "algorithm": hash_alg, "flags": hash_flags,
                "salt": salt.hex(), "stored_digest": digest.hex(),
                "calculated_digest": actual.hex(), "matches": actual == digest,
            })
        elif tag == 0:
            require(len(entry) >= 32, "Truncated property descriptor")
            key_len, value_len = struct.unpack_from(">QQ", entry, 16)
            strings = region(entry, 32, key_len + 1 + value_len + 1)
            require(strings[key_len] == strings[-1] == 0, "Invalid property terminators")
            key = strings[:key_len].decode("utf-8")
            require(key not in properties, "Duplicate AVB property")
            properties[key] = strings[key_len + 1:-1].decode("utf-8")
        else:
            raise ValueError(f"Unexpected descriptor tag {tag}")
        position += len(entry)
    require(len(hashes_found) == 1 and hashes_found[0]["partition_name"] == "boot",
            "Expected one boot hash descriptor")
    auth_hash_valid = signature_valid = None
    if algorithm == 0:
        require(auth_size == hash_size == sig_size == key_size == keymeta_size == 0,
                "Unsigned metadata unexpectedly contains authentication data")
    else:
        require(hash_size == 32 and sig_size == 512 and key_size == 1032,
                "Unexpected SHA256_RSA4096 layout")
        signed_data = meta[:256] + aux
        auth_hash_valid = hashlib.sha256(signed_data).digest() == region(auth, hash_off, hash_size)
        key = region(aux, key_off, key_size)
        bits = struct.unpack_from(">I", key)[0]
        require(bits == 4096, "Unexpected RSA key size")
        modulus = int.from_bytes(key[8:8 + bits // 8], "big")
        public_key = rsa.RSAPublicNumbers(65537, modulus).public_key()
        try:
            public_key.verify(region(auth, sig_off, sig_size), signed_data,
                              padding.PKCS1v15(), hashes.SHA256())
            signature_valid = True
        except InvalidSignature:
            signature_valid = False
    integrity = all(h["matches"] for h in hashes_found)
    if algorithm != 0:
        integrity = integrity and auth_hash_valid and signature_valid
    return {
        "original_image_bytes": original, "vbmeta_offset": offset,
        "vbmeta_bytes": size, "algorithm_type": algorithm,
        "algorithm": "NONE" if algorithm == 0 else "SHA256_RSA4096",
        "authentication_present": algorithm != 0,
        "authentication_hash_valid": auth_hash_valid,
        "signature_matches_embedded_key": signature_valid,
        "trusted_OEM_key_verified": False,
        "vbmeta_flags": flags,
        "rollback_index": struct.unpack_from(">Q", meta, 112)[0],
        "rollback_index_location": struct.unpack_from(">I", meta, 124)[0],
        "descriptor_tags": descriptor_tags, "properties": properties,
        "hash_descriptors": hashes_found, "integrity_checks_pass": bool(integrity),
    }
