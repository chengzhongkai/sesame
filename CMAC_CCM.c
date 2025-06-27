#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define SSM_SEG_PARSING_TYPE_PLAINTEXT (1)
#define SSM_SEG_PARSING_TYPE_CIPHERTEXT (2)
#define LAST_INDEX (BLOCK_SIZE - 1)
#define BLOCK_SIZE 16
#define CCM_TAG_LENGTH (4)
#define CCM_ENCRYPT 0
#define CCM_DECRYPT 1
#define MBEDTLS_ERR_CCM_BAD_INPUT -0x000D 
#define UPDATE_CBC_MAC_1                                                                                                                                                                                                                                      \
    for (i = 0; i < 16; i++)                                                                                                                                                                                                                                  \
        y[i] ^= b[i];                                                                                                                                                                                                                                         \
                                                                                                                                                                                                                                                              \
    if ((ret = aes_ecb_encrypt(key, y, y)) != 0)                                                                                                                                                                                                              \
        return (ret);

#define CTR_CRYPT_1(dst, src, len)                                                                                                                                                                                                                            \
    if ((ret = aes_ecb_encrypt(key, ctr, b)) != 0)                                                                                                                                                                                                            \
        return (ret);                                                                                                                                                                                                                                         \
                                                                                                                                                                                                                                                              \
    for (i = 0; i < len; i++)                                                                                                                                                                                                                                 \
        dst[i] = src[i] ^ b[i];

// https://www.onlinegdb.com/online_c_compiler
// https://github.com/CANDY-HOUSE/SesameSDK_ESP32_with_DemoApp
// https://github.com/CANDY-HOUSE/API_document/blob/master/SesameOS3/bluetooth.md
typedef enum
{
    SSM_ITEM_CODE_NONE = 0,
    SSM_ITEM_CODE_REGISTRATION = 1,
    SSM_ITEM_CODE_LOGIN = 2,
    SSM_ITEM_CODE_USER = 3,
    SSM_ITEM_CODE_HISTORY = 4,
    SSM_ITEM_CODE_VERSION_DETAIL = 5,
    SSM_ITEM_CODE_DISCONNECT_REBOOT_NOW = 6,
    SSM_ITEM_CODE_ENABLE_DFU = 7,
    SSM_ITEM_CODE_TIME = 8,
    SSM_ITEM_CODE_INITIAL = 14,
    SSM_ITEM_CODE_MAGNET = 17,
    SSM_ITEM_CODE_MECH_SETTING = 80,
    SSM_ITEM_CODE_MECH_STATUS = 81,
    SSM_ITEM_CODE_LOCK = 82,
    SSM_ITEM_CODE_UNLOCK = 83,
    SSM2_ITEM_OPS_TIMER_SETTING = 92,
} ssm_item_code_e;

typedef enum
{
    SSM_NOUSE = 0,
    SSM_DISCONNECTED = 1,
    SSM_SCANNING = 2,
    SSM_CONNECTING = 3,
    SSM_CONNECTED = 4,
    SSM_LOGGIN = 5,
    SSM_LOCKED = 6,
    SSM_UNLOCKED = 7,
    SSM_MOVED = 8,
} device_status_t;

typedef unsigned char uint8_t;

static unsigned const char const_Zero[BLOCK_SIZE] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                                                     0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00};
static unsigned const char const_Rb[BLOCK_SIZE] = {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                                                   0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x87};

const unsigned char sbox[256] = {
    // 0     1    2      3     4    5     6     7      8    9     A      B    C     D     E     F
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,  // 0
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,  // 1
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,  // 2
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,  // 3
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,  // 4
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,  // 5
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,  // 6
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,  // 7
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,  // 8
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,  // 9
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,  // A
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,  // B
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,  // C
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,  // D
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,  // E
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16}; // F

// inverse sbox
const unsigned char rsbox[256] =
    {0x52, 0x09, 0x6a, 0xd5, 0x30, 0x36, 0xa5, 0x38, 0xbf, 0x40, 0xa3, 0x9e, 0x81, 0xf3, 0xd7, 0xfb, 0x7c, 0xe3, 0x39, 0x82, 0x9b, 0x2f, 0xff, 0x87, 0x34, 0x8e, 0x43, 0x44, 0xc4, 0xde, 0xe9, 0xcb, 0x54, 0x7b, 0x94, 0x32, 0xa6, 0xc2, 0x23, 0x3d, 0xee, 0x4c, 0x95, 0x0b, 0x42, 0xfa, 0xc3, 0x4e, 0x08, 0x2e, 0xa1, 0x66, 0x28, 0xd9, 0x24, 0xb2, 0x76, 0x5b, 0xa2, 0x49, 0x6d, 0x8b, 0xd1, 0x25, 0x72, 0xf8, 0xf6, 0x64, 0x86, 0x68, 0x98, 0x16, 0xd4, 0xa4, 0x5c, 0xcc, 0x5d, 0x65, 0xb6, 0x92, 0x6c, 0x70, 0x48, 0x50, 0xfd, 0xed, 0xb9, 0xda, 0x5e, 0x15, 0x46, 0x57, 0xa7, 0x8d, 0x9d, 0x84, 0x90, 0xd8, 0xab, 0x00, 0x8c, 0xbc, 0xd3, 0x0a, 0xf7, 0xe4, 0x58, 0x05, 0xb8, 0xb3, 0x45, 0x06, 0xd0, 0x2c, 0x1e, 0x8f, 0xca, 0x3f, 0x0f, 0x02, 0xc1, 0xaf, 0xbd, 0x03, 0x01, 0x13, 0x8a, 0x6b, 0x3a, 0x91, 0x11, 0x41, 0x4f, 0x67, 0xdc, 0xea, 0x97, 0xf2, 0xcf, 0xce, 0xf0, 0xb4, 0xe6, 0x73, 0x96, 0xac, 0x74, 0x22, 0xe7, 0xad, 0x35, 0x85, 0xe2, 0xf9, 0x37, 0xe8, 0x1c, 0x75, 0xdf, 0x6e, 0x47, 0xf1, 0x1a, 0x71, 0x1d, 0x29, 0xc5, 0x89, 0x6f, 0xb7, 0x62, 0x0e, 0xaa, 0x18, 0xbe, 0x1b, 0xfc, 0x56, 0x3e, 0x4b, 0xc6, 0xd2, 0x79, 0x20, 0x9a, 0xdb, 0xc0, 0xfe, 0x78, 0xcd, 0x5a, 0xf4, 0x1f, 0xdd, 0xa8, 0x33, 0x88, 0x07, 0xc7, 0x31, 0xb1, 0x12, 0x10, 0x59, 0x27, 0x80, 0xec, 0x5f, 0x60, 0x51, 0x7f, 0xa9, 0x19, 0xb5, 0x4a, 0x0d, 0x2d, 0xe5, 0x7a, 0x9f, 0x93, 0xc9, 0x9c, 0xef, 0xa0, 0xe0, 0x3b, 0x4d, 0xae, 0x2a, 0xf5, 0xb0, 0xc8, 0xeb, 0xbb, 0x3c, 0x83, 0x53, 0x99, 0x61, 0x17, 0x2b, 0x04, 0x7e, 0xba, 0x77, 0xd6, 0x26, 0xe1, 0x69, 0x14, 0x63, 0x55, 0x21, 0x0c, 0x7d};
typedef struct mech_status_s
{
    uint16_t battery;
    int16_t target;               // 馬達想到的地方
    int16_t position;             // 感測器同步到的最新角度
    uint8_t is_clutch_failed : 1; // 電磁鐵作棟是否成功(沒用到)
    uint8_t is_lock_range : 1;    // 在關鎖位置
    uint8_t is_unlock_range : 1;  // 在開鎖位置
    uint8_t is_critical : 1;      // 開關鎖時間超時，馬達停轉
    uint8_t is_stop : 1;          // 把手角度沒有變化
    uint8_t is_low_battery : 1;   // 低電量(<5V)
    uint8_t is_clockwise : 1;     // 馬達轉動方向
} mech_status_t;                  // total 7 bytes

typedef struct
{
    int64_t count;
    uint8_t nouse;
    uint8_t random_code[4];
} SSM_CCM_NONCE;

typedef struct
{
    uint8_t token[16];
    SSM_CCM_NONCE encrypt;
    SSM_CCM_NONCE decrypt;
} SesameBleCipher;
// round constant
const unsigned char Rcon[10] = {
    0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36};
typedef struct
{
    uint8_t device_uuid[16];
    uint8_t public_key[64];
    uint8_t device_secret[16];
    uint8_t addr[6];
    volatile uint8_t device_status;
    SesameBleCipher cipher;
    mech_status_t mech_status;
    uint16_t c_offset;
    uint8_t b_buf[80]; /// max command size is register(80 Bytes).
    uint8_t conn_id;
} sesame;

typedef void (*ssm_action)(sesame *ssm);
struct ssm_env_tag
{
    sesame ssm;
    ssm_action ssm_cb__;
};
struct ssm_env_tag *p_ssms_env = NULL;

static uint8_t tag_esp32[] = { 'S', 'E', 'S', 'A', 'M', 'E', ' ', 'E', 'S', 'P', '3', '2' };
static uint8_t additional_data[] = { 0x00 };

static void generate_subkey(const unsigned char *key, unsigned char *K1, unsigned char *K2);
static void ssm_initial_handle(sesame *ssm, uint8_t cmd_it_code);
static void padding(const unsigned char *lastb, unsigned char *pad, int length);
static void leftshift_onebit(const unsigned char *input, unsigned char *output);
unsigned char galois_mul2(unsigned char value);
void xor_128(const unsigned char *a, const unsigned char *b, unsigned char *out);
void aes_enc_dec(unsigned char *state, unsigned char *key, unsigned char dir);
void AES_128_ENC(unsigned const char *key, unsigned const char *msg, unsigned char *cipher);
void AES_CMAC(const unsigned char *key, const unsigned char *input, int length,
              unsigned char *mac);
void ssm_init();
void talk_to_ssm(sesame * ssm, uint8_t parsing_type);
int aes_ccm_encrypt_and_tag(const unsigned char * key, const unsigned char * iv, size_t iv_len, const unsigned char * add, size_t add_len, const unsigned char * input, size_t length, unsigned char * output, unsigned char * tag, size_t tag_len);
static int ccm_auth_crypt(int mode, const unsigned char * key, const unsigned char * iv, size_t iv_len, const unsigned char * add, size_t add_len, const unsigned char * input, size_t length, unsigned char * output, unsigned char * tag, size_t tag_len);
static int aes_ecb_encrypt(const uint8_t * pKey, uint8_t * input, uint8_t * output);

static int aes_ecb_encrypt(const uint8_t * pKey, uint8_t * input, uint8_t * output)
{
    printf("[aes_ecb_encrypt][pKey: ");
    for (int i = 0; i < 16; i++)
    {
        printf("%02x",  pKey[i]);
    }
    printf("]\n");

    AES_128_ENC(pKey, input, output);

    return 0;
}
/*
 * Authenticated encryption or decryption
 */
static int ccm_auth_crypt(int mode, const unsigned char * key, const unsigned char * iv, size_t iv_len, const unsigned char * add, size_t add_len, const unsigned char * input, size_t length, unsigned char * output, unsigned char * tag, size_t tag_len)
{
    int ret;
    unsigned char i;
    unsigned char q;
    size_t len_left;
    unsigned char b[16];
    unsigned char y[16];
    unsigned char ctr[16];
    const unsigned char * src;
    unsigned char * dst;

    /*
     * Check length requirements: SP800-38C A.1
     * Additional requirement: a < 2^16 - 2^8 to simplify the code.
     * 'length' checked later (when writing it to the first block)
     */
    if (tag_len < 4 || tag_len > 16 || tag_len % 2 != 0)
        return (MBEDTLS_ERR_CCM_BAD_INPUT);

    /* Also implies q is within bounds */
    if (iv_len < 7 || iv_len > 13)
        return (MBEDTLS_ERR_CCM_BAD_INPUT);

    if (add_len > 0xFF00)
        return (MBEDTLS_ERR_CCM_BAD_INPUT);

    q = 16 - 1 - (unsigned char) iv_len;

    /*
     * First block B_0:
     * 0        .. 0        flags
     * 1        .. iv_len   nonce (aka iv)
     * iv_len+1 .. 15       length
     *
     * With flags as (bits):
     * 7        0
     * 6        add present?
     * 5 .. 3   (t - 2) / 2
     * 2 .. 0   q - 1
     */
    b[0] = 0;
    b[0] |= (add_len > 0) << 6;
    b[0] |= ((tag_len - 2) / 2) << 3;
    b[0] |= q - 1;

    memcpy(b + 1, iv, iv_len);

    for (i = 0, len_left = length; i < q; i++, len_left >>= 8)
        b[15 - i] = (unsigned char) (len_left & 0xFF);

    if (len_left > 0)
        return (MBEDTLS_ERR_CCM_BAD_INPUT);

    /* Start CBC-MAC with first block */
    memset(y, 0, 16);
    printf("[ccm_auth_crypt][b: ");
    for (int i = 0; i < 16; i++)
    {
        printf("%02x", y[i]);
    }
    printf("]\n");
    UPDATE_CBC_MAC_1;
    printf("[ccm_auth_crypt][b: ");
    for (int i = 0; i < 16; i++)
    {
        printf("%02x", y[i]);
    }
    printf("]\n");
    /*
     * If there is additional data, update CBC-MAC with
     * add_len, add, 0 (padding to a block boundary)
     */
    if (add_len > 0)
    {
        size_t use_len;
        len_left = add_len;
        src      = add;

        memset(b, 0, 16);
        b[0] = (unsigned char) ((add_len >> 8) & 0xFF);
        b[1] = (unsigned char) ((add_len) &0xFF);

        use_len = len_left < 16 - 2 ? len_left : 16 - 2;
        memcpy(b + 2, src, use_len);
        len_left -= use_len;
        src += use_len;

        UPDATE_CBC_MAC_1;

        while (len_left > 0)
        {
            use_len = len_left > 16 ? 16 : len_left;

            memset(b, 0, 16);
            memcpy(b, src, use_len);
            UPDATE_CBC_MAC_1;

            len_left -= use_len;
            src += use_len;
        }
    }

    /*
     * Prepare counter block for encryption:
     * 0        .. 0        flags
     * 1        .. iv_len   nonce (aka iv)
     * iv_len+1 .. 15       counter (initially 1)
     *
     * With flags as (bits):
     * 7 .. 3   0
     * 2 .. 0   q - 1
     */
    ctr[0] = q - 1;
    memcpy(ctr + 1, iv, iv_len);
    memset(ctr + 1 + iv_len, 0, q);
    ctr[15] = 1;

    /*
     * Authenticate and {en,de}crypt the message.
     *
     * The only difference between encryption and decryption is
     * the respective order of authentication and {en,de}cryption.
     */
    len_left = length;
    src      = input;
    dst      = output;

    while (len_left > 0)
    {
        size_t use_len = len_left > 16 ? 16 : len_left;

        if (mode == CCM_ENCRYPT)
        {
            memset(b, 0, 16);
            memcpy(b, src, use_len);
            UPDATE_CBC_MAC_1;
        }

        CTR_CRYPT_1(dst, src, use_len);

        if (mode == CCM_DECRYPT)
        {
            memset(b, 0, 16);
            memcpy(b, dst, use_len);
            UPDATE_CBC_MAC_1;
        }

        dst += use_len;
        src += use_len;
        len_left -= use_len;

        /*
         * Increment counter.
         * No need to check for overflow thanks to the length check above.
         */
        for (i = 0; i < q; i++)
            if (++ctr[15 - i] != 0)
                break;
    }

    /*
     * Authentication: reset counter and crypt/mask internal tag
     */
    for (i = 0; i < q; i++)
        ctr[15 - i] = 0;

    CTR_CRYPT_1(y, y, 16);
    memcpy(tag, y, tag_len);

    return (0);
}
int aes_ccm_encrypt_and_tag(const unsigned char * key, const unsigned char * iv, size_t iv_len, const unsigned char * add, size_t add_len, const unsigned char * input, size_t length, unsigned char * output, unsigned char * tag, size_t tag_len)
{
    return (ccm_auth_crypt(CCM_ENCRYPT, key, iv, iv_len, add, add_len, input, length, output, tag, tag_len));
}
void talk_to_ssm(sesame * ssm, uint8_t parsing_type) {
    if (parsing_type == SSM_SEG_PARSING_TYPE_CIPHERTEXT) {
        printf("[talk_to_ssm-->][plat data: ");
        for (int i = 0; i < ssm->c_offset; i++)
        {
            printf("%02x", ssm->b_buf[i]);
        }
        printf("]\n");
        /*
        key: ssm->cipher.token
        iv: ssm->cipher.encrypt.count
        iv_len: 13
        additional_data: additional_data
        length: ssm->c_offset
        input: ssm->b_buf
        output: ssm->b_buf
        tag: ssm->b_buf + ssm->c_offset
        tag_len: CCM_TAG_LENGTH 4

        */
       printf("[talk_to_ssm][key: ");
       for (int i = 0; i < 4; i++)
       {
           printf("%02x", ssm->cipher.token[i]);
       }
       printf("]\n");

       const unsigned char * vxp=(const unsigned char *) &ssm->cipher.encrypt;
       printf("[talk_to_ssm][iv: ");
       for (int i = 0; i < 13; i++)
       {
           printf("%02x", vxp[i]);
       }
       printf("]\n");
       printf("[talk_to_ssm][data: ");
       for (int i = 0; i < ssm->c_offset; i++)
       {
           printf("%02x", ssm->b_buf[i]);
       }
       printf("]\n");

        aes_ccm_encrypt_and_tag(ssm->cipher.token, (const unsigned char *) &ssm->cipher.encrypt, 13, additional_data, 1, ssm->b_buf, ssm->c_offset, ssm->b_buf, ssm->b_buf + ssm->c_offset, CCM_TAG_LENGTH);
        ssm->cipher.encrypt.count++;
        ssm->c_offset = ssm->c_offset + CCM_TAG_LENGTH;
    }

    uint8_t * data = ssm->b_buf;
    uint16_t remain = ssm->c_offset;
    uint16_t len = remain;
    uint8_t tmp_v[20] = { 0 };
    uint16_t len_l;

    printf("[talk_to_ssm][data: ");
    for (int i = 0; i < remain; i++)
    {
        printf("%02x", ssm->b_buf[i]);
    }
    printf("]\n");

    // while (remain) {
    //     if (remain <= 19) {
    //         tmp_v[0] = parsing_type << 1u;
    //         len_l = 1 + remain;
    //     } else {
    //         tmp_v[0] = 0;
    //         len_l = 20;
    //     }
    //     if (remain == len) {
    //         tmp_v[0] |= 1u;
    //     }
    //     memcpy(&tmp_v[1], data, len_l - 1);
    //     esp_ble_gatt_write(ssm, tmp_v, len_l);
    //     remain -= (len_l - 1);
    //     data += (len_l - 1);
    // }
}



void ssm_init()
{
    p_ssms_env = (struct ssm_env_tag *)calloc(1, sizeof(struct ssm_env_tag));
    if (p_ssms_env == NULL)
    {
    }
    //p_ssms_env->ssm_cb__ = ssm_action_cb; // callback: ssm_action_handle
    p_ssms_env->ssm.conn_id = 0xFF;       // 0xFF: not connected
    p_ssms_env->ssm.device_status = SSM_NOUSE;
    p_ssms_env->ssm.c_offset = 0; // reset command offset

    printf("[ssm_init][SUCCESS]\n");
}

unsigned char galois_mul2(unsigned char value)
{
    if (value >> 7)
    {
        return ((value << 1) ^ 0x1b);
    }
    else
        return (value << 1);
}

static void leftshift_onebit(const unsigned char *input, unsigned char *output)
{
    int i;
    unsigned char overflow = 0;

    for (i = LAST_INDEX; i >= 0; i--)
    {
        output[i] = input[i] << 1;
        output[i] |= overflow;
        overflow = (input[i] & 0x80) ? 1 : 0;
    }
    return;
}

static void padding(const unsigned char *lastb, unsigned char *pad, int length)
{
    int j;

    /* original last block */
    for (j = 0; j < BLOCK_SIZE; j++)
    {
        if (j < length)
        {
            pad[j] = lastb[j];
        }
        else if (j == length)
        {
            pad[j] = 0x80;
        }
        else
        {
            pad[j] = 0x00;
        }
    }
}

// master/main/sesame/ssm_cmd.c
void send_login_cmd_to_ssm(sesame *ssm)
{
    printf("[send_login_cmd_to_ssm]\n");

    ssm->b_buf[0] = SSM_ITEM_CODE_LOGIN;

    AES_CMAC(ssm->device_secret, (const unsigned char *)ssm->cipher.decrypt.random_code, 4, ssm->cipher.token);
    memcpy(&ssm->b_buf[1], ssm->cipher.token, 4);
    printf("[send_login_cmd_to_ssm][token: ");
    for (int i = 0; i < 4; i++)
    {
        printf("%02x", ssm->cipher.token[i]);
    }
    printf("]\n");
    ssm->c_offset = 5;

    printf("[send_login_cmd_to_ssm][data: ");
    for (int i = 0; i < 5; i++)
    {
        printf("%02x", ssm->b_buf[i]);
    }
    printf("]\n"); 
    talk_to_ssm(ssm, SSM_SEG_PARSING_TYPE_PLAINTEXT);
}

void ssm_lock(uint8_t * tag, uint8_t tag_length) {
    // ESP_LOGI(TAG, "[ssm][ssm_lock][%s]", SSM_STATUS_STR(p_ssms_env->ssm.device_status));
    sesame * ssm = &p_ssms_env->ssm;
    if (ssm->device_status >= SSM_LOGGIN) {
        if (tag_length == 0) {
            tag = tag_esp32;
            tag_length = sizeof(tag_esp32);
        }
        ssm->b_buf[0] = SSM_ITEM_CODE_LOCK;
        ssm->b_buf[1] = tag_length;
        ssm->c_offset = tag_length + 2;
        memcpy(ssm->b_buf + 2, tag, tag_length);
        talk_to_ssm(ssm, SSM_SEG_PARSING_TYPE_CIPHERTEXT);
    }
}

// master/main/utils/aes-cbc-cmac.c#L86
void AES_CMAC(const unsigned char *key, const unsigned char *input, int length,
              unsigned char *mac)
{

    // key: device_secret
    // input: random_code
    // length: 4
    // mac: ssm->cipher.token

    unsigned char X[BLOCK_SIZE], Y[BLOCK_SIZE], M_last[BLOCK_SIZE], padded[BLOCK_SIZE];
    unsigned char K1[BLOCK_SIZE], K2[BLOCK_SIZE];
    int n, i, flag;
    printf("[AES_CMAC][input: ");
    for (int i = 0; i < length; i++)
    {
        printf("%02x", input[i]);
    }
    printf("]\n"); 
    generate_subkey(key, K1, K2);

    printf("[AES_CMAC][key: ");
    for (int i = 0; i < BLOCK_SIZE; i++)
    {
        printf("%02x", key[i]);
    }
    printf("]\n");  
    printf("[AES_CMAC][input: ");
    for (int i = 0; i < length; i++)
    {
        printf("%02x", input[i]);
    }
    printf("]\n");   
    // printf("[AES_CMAC][K1: ");
    // for (int i = 0; i < BLOCK_SIZE; i++)
    // {
    //     printf("%02x", K1[i]);
    // }
    // printf("]\n");
    // printf("[AES_CMAC][K2: ");
    // for (int i = 0; i < BLOCK_SIZE; i++)
    // {
    //     printf("%02x", K2[i]);
    // }
    // printf("]\n");

    n = (length + LAST_INDEX) / BLOCK_SIZE; /* n is number of rounds */

    if (n == 0)
    {
        n = 1;
        flag = 0;
    }
    else
    {
        if ((length % BLOCK_SIZE) == 0)
        { /* last block is a complete block */
            flag = 1;
        }
        else
        { /* last block is not complete block */
            flag = 0;
        }
    }

    if (flag)
    { /* last block is complete block */
        xor_128(&input[BLOCK_SIZE * (n - 1)], K1, M_last);
    }
    else
    {
        padding(&input[BLOCK_SIZE * (n - 1)], padded, length % BLOCK_SIZE);
        xor_128(padded, K2, M_last);
    }

    memset(X, 0, BLOCK_SIZE);
    for (i = 0; i < n - 1; i++)
    {
        xor_128(X, &input[BLOCK_SIZE * i], Y); /* Y := Mi (+) X  */
        AES_128_ENC(key, Y, X);                /* X := AES-128(KEY, Y); */
    }
    printf("[AES_CMAC][x: ");
    for (int i = 0; i < BLOCK_SIZE; i++)
    {
        printf("%02x", X[i]);
    }
    printf("]\n");
    printf("[AES_CMAC][y: ");
    for (int i = 0; i < BLOCK_SIZE; i++)
    {
        printf("%02x", Y[i]);
    }
    printf("]\n");
    xor_128(X, M_last, Y);
    AES_128_ENC(key, Y, X);

    memcpy(mac, X, BLOCK_SIZE);
}

static void generate_subkey(const unsigned char *key, unsigned char *K1, unsigned char *K2)
{
    unsigned char L[BLOCK_SIZE];
    unsigned char tmp[BLOCK_SIZE];

    AES_128_ENC(key, const_Zero, L);

    if ((L[0] & 0x80) == 0)
    { /* If MSB(L) = 0, then K1 = L << 1 */
        leftshift_onebit(L, K1);
    }
    else
    { /* Else K1 = ( L << 1 ) (+) Rb */

        leftshift_onebit(L, tmp);
        xor_128(tmp, const_Rb, K1);
    }

    if ((K1[0] & 0x80) == 0)
    {
        leftshift_onebit(K1, K2);
    }
    else
    {
        leftshift_onebit(K1, tmp);
        xor_128(tmp, const_Rb, K2);
    }
    return;
}

void AES_128_ENC(unsigned const char *key, unsigned const char *msg, unsigned char *cipher)
{
    unsigned char key_copy[BLOCK_SIZE];
    memcpy(cipher, msg, BLOCK_SIZE);
    memcpy(key_copy, key, BLOCK_SIZE);
    // 0 for encryption
    // cipher is also the output buffer
    aes_enc_dec(cipher, key_copy, 0);
}

// This function only implements AES-128 encryption and decryption

void aes_enc_dec(unsigned char *state, unsigned char *key, unsigned char dir)
{
    unsigned char buf1, buf2, buf3, buf4, round, i;

    // In case of decryption
    if (dir)
    {
        // compute the last key of encryption before starting the decryption
        for (round = 0; round < 10; round++)
        {
            // key schedule
            key[0] = sbox[key[13]] ^ key[0] ^ Rcon[round];
            key[1] = sbox[key[14]] ^ key[1];
            key[2] = sbox[key[15]] ^ key[2];
            key[3] = sbox[key[12]] ^ key[3];
            for (i = 4; i < 16; i++)
            {
                key[i] = key[i] ^ key[i - 4];
            }
        }

        // first Addroundkey
        for (i = 0; i < 16; i++)
        {
            state[i] = state[i] ^ key[i];
        }
    }

    // main loop
    for (round = 0; round < 10; round++)
    {
        if (dir)
        {
            // Inverse key schedule
            for (i = 15; i > 3; --i)
            {
                key[i] = key[i] ^ key[i - 4];
            }
            key[0] = sbox[key[13]] ^ key[0] ^ Rcon[9 - round];
            key[1] = sbox[key[14]] ^ key[1];
            key[2] = sbox[key[15]] ^ key[2];
            key[3] = sbox[key[12]] ^ key[3];
        }
        else
        {
            for (i = 0; i < 16; i++)
            {
                // with shiftrow i+5 mod 16
                state[i] = sbox[state[i] ^ key[i]];
            }
            // shift rows
            buf1 = state[1];
            state[1] = state[5];
            state[5] = state[9];
            state[9] = state[13];
            state[13] = buf1;

            buf1 = state[2];
            buf2 = state[6];
            state[2] = state[10];
            state[6] = state[14];
            state[10] = buf1;
            state[14] = buf2;

            buf1 = state[15];
            state[15] = state[11];
            state[11] = state[7];
            state[7] = state[3];
            state[3] = buf1;
        }
        // mixcol - inv mix
        if ((round > 0 && dir) || (round < 9 && !dir))
        {
            for (i = 0; i < 4; i++)
            {
                buf4 = (i << 2);
                if (dir)
                {
                    // precompute for decryption
                    buf1 = galois_mul2(galois_mul2(state[buf4] ^ state[buf4 + 2]));
                    buf2 = galois_mul2(galois_mul2(state[buf4 + 1] ^ state[buf4 + 3]));
                    state[buf4] ^= buf1;
                    state[buf4 + 1] ^= buf2;
                    state[buf4 + 2] ^= buf1;
                    state[buf4 + 3] ^= buf2;
                }
                // in all cases
                buf1 = state[buf4] ^ state[buf4 + 1] ^ state[buf4 + 2] ^ state[buf4 + 3];
                buf2 = state[buf4];
                buf3 = state[buf4] ^ state[buf4 + 1];
                buf3 = galois_mul2(buf3);
                printf("%d,%d,%d",buf1,buf2,buf3);
                state[buf4] = state[buf4] ^ buf3 ^ buf1;
                buf3 = state[buf4 + 1] ^ state[buf4 + 2];
                buf3 = galois_mul2(buf3);
                state[buf4 + 1] = state[buf4 + 1] ^ buf3 ^ buf1;
                buf3 = state[buf4 + 2] ^ state[buf4 + 3];
                buf3 = galois_mul2(buf3);
                state[buf4 + 2] = state[buf4 + 2] ^ buf3 ^ buf1;
                buf3 = state[buf4 + 3] ^ buf2;
                buf3 = galois_mul2(buf3);
                state[buf4 + 3] = state[buf4 + 3] ^ buf3 ^ buf1;
            }
        }

        if (dir)
        {
            // Inv shift rows
            //  Row 1
            buf1 = state[13];
            state[13] = state[9];
            state[9] = state[5];
            state[5] = state[1];
            state[1] = buf1;
            // Row 2
            buf1 = state[10];
            buf2 = state[14];
            state[10] = state[2];
            state[14] = state[6];
            state[2] = buf1;
            state[6] = buf2;
            // Row 3
            buf1 = state[3];
            state[3] = state[7];
            state[7] = state[11];
            state[11] = state[15];
            state[15] = buf1;

            for (i = 0; i < 16; i++)
            {
                // with shiftrow i+5 mod 16
                state[i] = rsbox[state[i]] ^ key[i];
            }
        }
        else
        {
            // key schedule
            key[0] = sbox[key[13]] ^ key[0] ^ Rcon[round];
            key[1] = sbox[key[14]] ^ key[1];
            key[2] = sbox[key[15]] ^ key[2];
            key[3] = sbox[key[12]] ^ key[3];
            for (i = 4; i < 16; i++)
            {
                key[i] = key[i] ^ key[i - 4];
            }
        }
    }
    if (!dir)
    {
        // last Addroundkey
        for (i = 0; i < 16; i++)
        {
            // with shiftrow i+5 mod 16
            state[i] = state[i] ^ key[i];
        } // enf for
    } // end if (!dir)
} // end function

void xor_128(const unsigned char *a, const unsigned char *b, unsigned char *out)
{
    int i;
    for (i = 0; i < BLOCK_SIZE; i++)
    {
        out[i] = a[i] ^ b[i];
    }
}

static void ssm_parse_publish(sesame *ssm, uint8_t cmd_it_code)
{
    switch (cmd_it_code)
    {
    case SSM_ITEM_CODE_INITIAL: // get 4 bytes random_code
        ssm_initial_handle(ssm, cmd_it_code);
        break;
    case SSM_ITEM_CODE_MECH_STATUS:
        printf("[ssm_parse_publish][SSM_ITEM_CODE_MECH_STATUS]");
        memcpy((void *)&(ssm->mech_status), ssm->b_buf, 7);
        device_status_t lockStatus = ssm->mech_status.is_lock_range ? SSM_LOCKED : (ssm->mech_status.is_unlock_range ? SSM_UNLOCKED : SSM_MOVED);
        if (ssm->device_status != lockStatus)
        {
            ssm->device_status = lockStatus;
            // p_ssms_env->ssm_cb__(ssm); // callback: ssm_action_handle
        }
        break;
    default:
        break;
    }
}

static void ssm_parse_response(sesame *ssm, uint8_t cmd_it_code)
{
    ssm->c_offset = ssm->c_offset - 1;
    memcpy(ssm->b_buf, ssm->b_buf + 1, ssm->c_offset);
    switch (cmd_it_code)
    {
    case SSM_ITEM_CODE_REGISTRATION:
        // handle_reg_data_from_ssm(ssm);
        break;
    case SSM_ITEM_CODE_LOGIN:
        ssm->device_status = SSM_LOGGIN;
        // p_ssms_env->ssm_cb__(ssm); // callback: ssm_action_handle
        break;
    case SSM_ITEM_CODE_HISTORY:
        if (ssm->c_offset == 0)
        { // 循環讀取 避免沒取完歷史
            return;
        }
        // todo send_read_history_cmd_to_ssm(ssm);
        break;
    default:
        break;
    }
}

static void ssm_initial_handle(sesame *ssm, uint8_t cmd_it_code)
{
    printf("[ssm_initial_handle][cmd_it_code: %d]", cmd_it_code);
    ssm->cipher.encrypt.nouse = 0; // reset cipher
    ssm->cipher.decrypt.nouse = 0;
    memcpy(ssm->cipher.encrypt.random_code, ssm->b_buf, 4);
    memcpy(ssm->cipher.decrypt.random_code, ssm->b_buf, 4);
    ssm->cipher.encrypt.count = 0;
    ssm->cipher.decrypt.count = 0;

    printf("[ssm_initial_handle][random_code:");
    for (int i = 0; i < 4; i++)
    {
        printf("%02x", ssm->cipher.encrypt.random_code[i]);
    }
    printf("]\n"); 

    if (p_ssms_env->ssm.device_secret[0] == 0)
    {
        // send_reg_cmd_to_ssm(ssm);
        return;
    }
    send_login_cmd_to_ssm(ssm);
}

int main()
{
    printf("Hello sesame.");
    ssm_init();

    sesame * ssm = &p_ssms_env->ssm;
    const uint8_t * p_data = (const uint8_t *)"\x03\x08\x0e\x54\xa4\x9c\x25"; // example data
    uint16_t len = 7;
    uint8_t source[16] = {0x4b,0xb2,0x73,0x93,0x5a,0xb6,0x02,0xea,0xce,0x93,0xa2,0x6d,0xb6,0xef,0x0f,0xde};
    memcpy(ssm->device_secret, source, 16); 

    memcpy(&ssm->b_buf[ssm->c_offset], p_data + 1, len - 1);
    ssm->c_offset += len - 1;
    uint8_t cmd_op_code = ssm->b_buf[0];
    uint8_t cmd_it_code = ssm->b_buf[1];

    ssm->c_offset = ssm->c_offset - 2;
    memcpy(ssm->b_buf, ssm->b_buf + 2, ssm->c_offset);
    printf("[ssm_parse_publish][cmd_it_code: %d]", cmd_it_code);
    ssm_parse_publish(ssm, cmd_it_code);

    ssm->device_status = SSM_LOGGIN;
    ssm_lock("myTag", 5); // lock without tag
    return 0;
}