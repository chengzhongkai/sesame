# -*- coding: utf-8 -*-

"""
A pure Python implementation of AES, CMAC, and CCM.

WARNING: This implementation is for educational purposes only.
It is not recommended for production use as it is not optimized
and may not be secure against side-channel attacks.
For production use, please use a well-vetted library like 'cryptography'.
"""

import math

# ==============================================================================
#  AES-128 Implementation (Required for CMAC and CCM)
#  This is a simplified implementation to make the code self-contained.
# ==============================================================================

class AES:
    """A pure Python implementation of AES-128."""

    # S-box and Inverse S-box
    S_BOX = (
        0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
        0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
        0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
        0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
        0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
        0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
        0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
        0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
        0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
        0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
        0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
        0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
        0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
        0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
        0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
        0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
    )

    # Rcon for key expansion
    RCON = (
        0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36
    )
    
    BLOCK_SIZE = 16
    KEY_SIZE = 16 # AES-128
    NUM_ROUNDS = 10 # For AES-128

    def __init__(self, key: bytes):
        if len(key) != self.KEY_SIZE:
            raise ValueError(f"Invalid key size. Key must be {self.KEY_SIZE} bytes.")
        self._key = key
        self._expanded_key = self._expand_key(key)

    def _sub_word(self, word):
        return [self.S_BOX[b] for b in word]

    def _rot_word(self, word):
        return word[1:] + word[:1]

    def _expand_key(self, key):
        key_words = [list(key[i:i+4]) for i in range(0, self.KEY_SIZE, 4)]
        
        for i in range(4, 4 * (self.NUM_ROUNDS + 1)):
            temp = list(key_words[i-1])
            if i % 4 == 0:
                temp = self._rot_word(temp)
                temp = self._sub_word(temp)
                temp[0] ^= self.RCON[i // 4]
            
            for j in range(4):
                temp[j] ^= key_words[i-4][j]
            key_words.append(temp)
        
        return [bytes(w) for w in key_words]

    def _bytes2matrix(self, text):
        return [list(text[i:i+4]) for i in range(0, len(text), 4)]

    def _matrix2bytes(self, matrix):
        return bytes(b for row in matrix for b in row)

    def _sub_bytes(self, state):
        for r in range(4):
            for c in range(4):
                state[r][c] = self.S_BOX[state[r][c]]

    def _shift_rows(self, state):
        state[0][1], state[1][1], state[2][1], state[3][1] = state[1][1], state[2][1], state[3][1], state[0][1]
        state[0][2], state[1][2], state[2][2], state[3][2] = state[2][2], state[3][2], state[0][2], state[1][2]
        state[0][3], state[1][3], state[2][3], state[3][3] = state[3][3], state[0][3], state[1][3], state[2][3]

    def _xtime(self, a):
        return (((a << 1) ^ 0x1B) & 0xFF) if (a & 0x80) else (a << 1)
        
    def _mix_columns(self, state):
        for i in range(4):
            t = state[i][0] ^ state[i][1] ^ state[i][2] ^ state[i][3]
            u = state[i][0]
            state[i][0] ^= t ^ self._xtime(state[i][0] ^ state[i][1])
            state[i][1] ^= t ^ self._xtime(state[i][1] ^ state[i][2])
            state[i][2] ^= t ^ self._xtime(state[i][2] ^ state[i][3])
            state[i][3] ^= t ^ self._xtime(state[i][3] ^ u)
            
    def _add_round_key(self, state, round_key):
        for r in range(4):
            for c in range(4):
                state[r][c] ^= round_key[r][c]

    def encrypt_block(self, plaintext: bytes) -> bytes:
        if len(plaintext) != self.BLOCK_SIZE:
            raise ValueError(f"Plaintext block must be {self.BLOCK_SIZE} bytes long.")
        
        state = self._bytes2matrix(plaintext)
        round_key = self._bytes2matrix(b"".join(self._expanded_key[0:4]))
        self._add_round_key(state, round_key)

        for i in range(1, self.NUM_ROUNDS):
            self._sub_bytes(state)
            self._shift_rows(state)
            self._mix_columns(state)
            round_key = self._bytes2matrix(b"".join(self._expanded_key[i*4:(i+1)*4]))
            self._add_round_key(state, round_key)
            
        self._sub_bytes(state)
        self._shift_rows(state)
        round_key = self._bytes2matrix(b"".join(self._expanded_key[self.NUM_ROUNDS*4:]))
        self._add_round_key(state, round_key)

        return self._matrix2bytes(state)

# ==============================================================================
#  Helper Functions
# ==============================================================================

def xor_bytes(a: bytes, b: bytes) -> bytes:
    """Performs XOR operation on two byte strings."""
    return bytes(x ^ y for x, y in zip(a, b))

def left_shift_bytes(data: bytes) -> bytes:
    """Performs a left bit shift on a byte string."""
    result = bytearray(len(data))
    carry = 0
    for i in range(len(data) - 1, -1, -1):
        next_carry = (data[i] & 0x80) >> 7
        result[i] = ((data[i] << 1) & 0xFF) | carry
        carry = next_carry
    return bytes(result)

# ==============================================================================
#  CMAC Implementation
# ==============================================================================

class CMAC:
    """
    A pure Python implementation of CMAC (Cipher-based Message Authentication Code).
    Based on NIST Special Publication 800-38B.
    """
    def __init__(self, key: bytes, cipher_class=AES):
        self.cipher = cipher_class(key)
        self.block_size = self.cipher.BLOCK_SIZE
        
        # Generate subkeys K1 and K2
        const_zero = bytes(self.block_size)
        const_rb = bytes([0]*(self.block_size-1) + [0x87])

        l = self.cipher.encrypt_block(const_zero)
        
        if (l[0] & 0x80) == 0:
            self.k1 = left_shift_bytes(l)
        else:
            self.k1 = xor_bytes(left_shift_bytes(l), const_rb)
            
        if (self.k1[0] & 0x80) == 0:
            self.k2 = left_shift_bytes(self.k1)
        else:
            self.k2 = xor_bytes(left_shift_bytes(self.k1), const_rb)
            
    def _pad(self, data: bytes) -> bytes:
        """Pads the data according to CMAC padding rules."""
        last_block_len = len(data) % self.block_size
        if last_block_len == 0 and len(data) > 0:
            return data
        
        padding_len = self.block_size - last_block_len
        padded = data + b'\x80' + b'\x00' * (padding_len - 1)
        return padded

    def generate(self, message: bytes) -> bytes:
        """Generates the CMAC tag for a given message."""
        num_blocks = math.ceil(len(message) / self.block_size) if len(message) > 0 else 1
        
        if num_blocks == 0: # Empty message
            is_padded = True
            last_block = self._pad(b'')
        else:
            is_padded = (len(message) % self.block_size != 0)
            
            if not is_padded and len(message) > 0:
                last_block_start = (num_blocks - 1) * self.block_size
                last_block = message[last_block_start:]
            else:
                padded_message = self._pad(message)
                last_block_start = (num_blocks - 1) * self.block_size
                last_block = padded_message[last_block_start:]
        
        m_blocks = [message[i:i+self.block_size] for i in range(0, (num_blocks-1) * self.block_size, self.block_size)]

        x = bytes(self.block_size)
        for block in m_blocks:
            y = xor_bytes(x, block)
            x = self.cipher.encrypt_block(y)
        
        if is_padded:
            final_block = xor_bytes(last_block, self.k2)
        else:
            final_block = xor_bytes(last_block, self.k1)
            
        y = xor_bytes(x, final_block)
        tag = self.cipher.encrypt_block(y)
        
        return tag

    def verify(self, message: bytes, tag: bytes) -> bool:
        """Verifies the CMAC tag for a given message."""
        generated_tag = self.generate(message)
        
        # Constant-time comparison
        if len(generated_tag) != len(tag):
            return False
        
        result = 0
        for x, y in zip(generated_tag, tag):
            result |= x ^ y
        return result == 0

# ==============================================================================
#  CCM Implementation
# ==============================================================================

class CCM:
    """
    A pure Python implementation of CCM (Counter with CBC-MAC).
    Based on NIST Special Publication 800-38C.
    """
    def __init__(self, key: bytes, nonce: bytes, mac_len: int = 16, cipher_class=AES):
        if not (4 <= mac_len <= 16 and mac_len % 2 == 0):
            raise ValueError("MAC length must be an even integer between 4 and 16.")
            
        self.cipher = cipher_class(key)
        self.block_size = self.cipher.BLOCK_SIZE
        self.mac_len = mac_len
        self.nonce = nonce
        
        # Check nonce length
        # L is the size in bytes of the message length field.
        # N is the size in bytes of the nonce. L + N = 15.
        # Here we fix L=4 (max message length 2^32-1), so N=11.
        # This is a common choice.
        self.L = 2
        if len(nonce) != 15 - self.L:
            raise ValueError(f"Nonce length must be {15 - self.L} bytes for L={self.L}.")

    def _format_b0(self, adata: bytes, mlen: int) -> bytes:
        """Formats the first block B0."""
        # A_len = len(adata)
        # q = mlen
        # Q is message length in bytes (here we use self.L)
        # N is nonce length in bytes
        # t is MAC length
        
        # Flags byte
        # Bit 7: Reserved (0)
        # Bit 6: Adata (1 if len(adata) > 0, else 0)
        # Bits 5-3: (t-2)/2
        # Bits 2-0: q-1 (where q = self.L)
        
        adata_flag = 1 if len(adata) > 0 else 0
        flags = (adata_flag << 6) | (((self.mac_len - 2) // 2) << 3) | (self.L - 1)

        b0 = bytearray()
        b0.append(flags)
        b0.extend(self.nonce)
        b0.extend(mlen.to_bytes(self.L, 'big'))
        
        return bytes(b0)
        
    def _format_auth_data(self, adata: bytes, m_data: bytes) -> bytes:
        """Formats the data to be authenticated (B1, B2, ...)."""
        auth_payload = bytearray()
        
        # Add associated data
        if len(adata) > 0:
            if len(adata) < (2**16 - 2**8):
                auth_payload.extend(len(adata).to_bytes(2, 'big'))
            elif len(adata) < (2**32):
                auth_payload.extend(b'\xff\xfe')
                auth_payload.extend(len(adata).to_bytes(4, 'big'))
            else: # len(adata) >= 2**32
                auth_payload.extend(b'\xff\xff')
                auth_payload.extend(len(adata).to_bytes(8, 'big'))

            auth_payload.extend(adata)
            
            # Pad with zeros to align to block size
            padding_len = self.block_size - (len(auth_payload) % self.block_size)
            if padding_len != self.block_size:
                 auth_payload.extend(b'\x00' * padding_len)
        
        # Add message data
        auth_payload.extend(m_data)
        
        # Pad with zeros to align to block size
        padding_len = self.block_size - (len(auth_payload) % self.block_size)
        if padding_len != self.block_size:
             auth_payload.extend(b'\x00' * padding_len)
        
        return bytes(auth_payload)

    def _ctr_crypt(self, data: bytes) -> bytes:
        """Performs CTR mode encryption/decryption."""
        num_blocks = math.ceil(len(data) / self.block_size)
        encrypted_data = bytearray()
        
        for i in range(num_blocks):
            # Format counter block A_i
            # Flags: 0...0 | L-1
            flags = self.L - 1
            counter_block = bytearray()
            counter_block.append(flags)
            counter_block.extend(self.nonce)
            counter_block.extend((i + 1).to_bytes(self.L, 'big'))
            
            # Keystream S_i = E(K, A_i)
            keystream = self.cipher.encrypt_block(bytes(counter_block))
            
            # XOR with data
            block = data[i * self.block_size : (i + 1) * self.block_size]
            encrypted_data.extend(xor_bytes(block, keystream))
        
        return bytes(encrypted_data)

    def encrypt(self, plaintext: bytes, associated_data: bytes = b"") -> tuple[bytes, bytes]:
        """
        Encrypts plaintext and generates an authentication tag.
        Returns: (ciphertext, tag)
        """
        if len(plaintext) > 2**(self.L * 8):
             raise ValueError("Plaintext is too long.")
             
        # Step 1: Generate CBC-MAC
        b0 = self._format_b0(associated_data, len(plaintext))
        auth_data = self._format_auth_data(associated_data, plaintext)
        
        # The data for CBC-MAC is b0 followed by the formatted auth_data
        full_auth_data = b0 + auth_data
        
        # CBC-MAC calculation
        x = bytes(self.block_size)
        for i in range(0, len(full_auth_data), self.block_size):
            block = full_auth_data[i:i+self.block_size]
            y = xor_bytes(x, block)
            x = self.cipher.encrypt_block(y)
        
        # T is the CBC-MAC result
        cbc_mac = x
        
        # Step 2: Generate keystream for tag encryption
        # A_0 block for S_0
        flags = self.L - 1
        a0 = bytearray()
        a0.append(flags)
        a0.extend(self.nonce)
        a0.extend((0).to_bytes(self.L, 'big'))
        
        s0 = self.cipher.encrypt_block(bytes(a0))
        
        # Step 3: Encrypt the message using CTR mode
        ciphertext = self._ctr_crypt(plaintext)
        
        # Step 4: Encrypt the CBC-MAC to get the final tag
        tag = xor_bytes(cbc_mac, s0)[:self.mac_len]
        
        return ciphertext, tag

    def decrypt(self, ciphertext: bytes, tag: bytes, associated_data: bytes = b"") -> bytes | None:
        """
        Decrypts ciphertext and verifies the authentication tag.
        Returns the plaintext if verification is successful, otherwise None.
        """
        if len(tag) != self.mac_len:
            raise ValueError("Invalid tag length")

        # Step 1: Decrypt the ciphertext to get the original plaintext
        # In CTR mode, decryption is the same as encryption
        plaintext = self._ctr_crypt(ciphertext)
        
        # Step 2: Recalculate the tag using the received data and compare
        # This is done in the same way as encryption
        b0 = self._format_b0(associated_data, len(plaintext))
        auth_data = self._format_auth_data(associated_data, plaintext)
        
        full_auth_data = b0 + auth_data
        
        x = bytes(self.block_size)
        for i in range(0, len(full_auth_data), self.block_size):
            block = full_auth_data[i:i+self.block_size]
            y = xor_bytes(x, block)
            x = self.cipher.encrypt_block(y)
        
        cbc_mac = x
        
        # Generate S_0
        flags = self.L - 1
        a0 = bytearray()
        a0.append(flags)
        a0.extend(self.nonce)
        a0.extend((0).to_bytes(self.L, 'big'))
        
        s0 = self.cipher.encrypt_block(bytes(a0))
        
        # Calculate expected tag
        expected_tag = xor_bytes(cbc_mac, s0)[:self.mac_len]
        
        # Constant-time comparison
        result = 0
        for x_byte, y_byte in zip(expected_tag, tag):
            result |= x_byte ^ y_byte

        if result == 0:
            return plaintext
        else:
            return None


# ==============================================================================
#  示例和测试
# ==============================================================================

if __name__ == '__main__':
    print("="*60)
    print(" CMAC (AES-128) Example")
    print("="*60)

    # NIST SP 800-38B Example D.1
    device_secret = bytes.fromhex("813f956d0729a31a8620271e23d90822")
    random_code = bytes.fromhex("8e4b3f7c")
    
    # Example 1: 0-byte message

    cmac = CMAC(device_secret, cipher_class=AES)
    token = cmac.generate(random_code)
    print(f"##################   01 Login   ########################")
    print(f"device_secret:{device_secret.hex()}")
    print(f"random_code:  {random_code.hex()}")
    print(f"token:     {token.hex()}")
    print(f"token:     a2e26d6ea935bf713ff7fa043bd56544")
    print("-" * 20+"\n"*2)


   
    # Encryption
    print(f"##################   02 Unlock   ########################")
    key_ccm = token
    nonce = bytes.fromhex(f"000000000000000000{random_code.hex()}")
    plaintext = b"\x53\x03abc"
    ccm_enc = CCM(key=key_ccm, nonce=nonce, mac_len=4, cipher_class=AES)
    ciphertext, tag_enc = ccm_enc.encrypt(plaintext=plaintext, associated_data=bytes([0]))
    
    print(f"cmd text: {plaintext.hex()}")
    print(f"Ciphertext: {ciphertext.hex()}")
    print(f"Ciphertext: 0fe85988a1")
    print(f"Tag:        {tag_enc.hex()}")
    print(f"Tag:        c8568b6b")
    
    print("-" * 20+"\n"*2)

    # Decryption
    print(f"##################   03 Read msg   ########################")
    ciphertext = bytes.fromhex(f"5be9380e92ef281570a55b")
    # nonce = bytes.fromhex(f"000000000000000000{random_code.hex()}")
    ccm_dec = CCM(key=key_ccm, nonce=nonce, mac_len=4, cipher_class=AES)
    decrypted_text = ccm_dec.decrypt(ciphertext=ciphertext[0:-4], tag=ciphertext[-4:], associated_data=bytes([0]))
    print(f"ciphertext text: {ciphertext[0:-4].hex()}")
    print(f"decrypted text: {decrypted_text.hex()}")
    print(f"decrypted text: 070200e4505d68")

