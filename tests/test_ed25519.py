"""The signatures updates are checked with (jcc/ed25519.py), against the test values published in RFC 8032, section 7.1."""
import time
import unittest

from jcc import ed25519

# (private key seed, public key, message, signature), RFC 8032 section 7.1, tests 1, 2 and 3.
VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


class TestTheRfcValues(unittest.TestCase):
    def test_public_keys_and_signatures_match_the_published_ones(self):
        for seed, public, message, signature in VECTORS:
            seed, public, message, signature = (bytes.fromhex(v) for v in (seed, public, message, signature))
            self.assertEqual(ed25519.public_key(seed), public)
            self.assertEqual(ed25519.sign(seed, message), signature)
            self.assertTrue(ed25519.verify(public, message, signature))

    def test_anything_changed_is_refused(self):
        seed, public, message, signature = (bytes.fromhex(v) for v in VECTORS[2])
        self.assertFalse(ed25519.verify(public, message + b"!", signature), "another message")
        self.assertFalse(ed25519.verify(public, message, signature[:-1] + bytes([signature[-1] ^ 1])), "a changed signature")
        other = bytes.fromhex(VECTORS[0][1])
        self.assertFalse(ed25519.verify(other, message, signature), "someone else's key")
        for odd in (b"", b"x" * 31, b"x" * 64):
            self.assertFalse(ed25519.verify(odd, message, signature))
            self.assertFalse(ed25519.verify(public, message, odd))
        self.assertFalse(ed25519.verify(None, message, signature))
        big_s = signature[:32] + (ed25519.L + 1).to_bytes(32, "little")
        self.assertFalse(ed25519.verify(public, message, big_s), "s must be below the group's order")

    def test_a_signature_is_checked_quickly_enough(self):
        seed, public, message, signature = (bytes.fromhex(v) for v in VECTORS[1])
        began = time.time()
        self.assertTrue(ed25519.verify(public, message, signature))
        self.assertLess(time.time() - began, 5.0)


if __name__ == "__main__":
    unittest.main()
