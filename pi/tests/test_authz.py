"""authz.py の単体テスト（BLE / MQTT 不要）。  実行: cd pi && python3 -m unittest -v"""
import json
import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from Crypto.PublicKey import ECC  # noqa: E402

import authz  # noqa: E402

NOW = 1_760_000_000  # 2025-10-09 08:53:20 UTC = 17:53 JST (木曜日)


def make_cmd(user, lock="sesame5_b", action="lock", ts=NOW, nonce=None, key=None, **extra):
    cmd = {"v": 1, "req_id": uuid.uuid4().hex, "user": user, "lock": lock, "action": action,
           "ts": ts, "nonce": nonce or uuid.uuid4().hex[:24]}
    cmd.update(extra)
    if key is not None:
        cmd["sig"] = authz.sign(cmd, key)
    return cmd


class AuthzTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "authz.json")
        self.alice_pem, alice_pub = authz.generate_keypair()
        self.bob_pem, bob_pub = authz.generate_keypair()
        self.alice = ECC.import_key(self.alice_pem)
        self.bob = ECC.import_key(self.bob_pem)
        self.cfg = {
            "enabled": True,
            "allowed_actions": ["lock", "unlock"],
            "clock_skew_sec": 60,
            "tz": "Asia/Tokyo",
            "limits": {"unlock_per_minute": 2, "unlock_per_hour": 5, "lock_per_minute": 10},
            "users": {
                "alice": {"enabled": True, "pubkey": alice_pub, "history_tag": "MQTT:alice",
                          "grants": [{"locks": ["sesame5_t", "sesame5_b"], "actions": ["lock", "unlock"]}]},
                "bob": {"enabled": True, "pubkey": bob_pub, "history_tag": "MQTT:bob",
                        "grants": [{"locks": ["sesame5_b"], "actions": ["lock", "unlock"],
                                    "schedule": {"days": ["Thu"], "hours": ["09:00-18:00"]},
                                    "valid_until": "2030-01-01T00:00:00+09:00"}]},
            },
        }
        self.write(self.cfg)
        self.az = authz.Authz(self.path, nonce_db=os.path.join(self.tmp.name, "n.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, cfg):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        os.utime(self.path, (NOW, NOW + getattr(self, "_bump", 0)))
        self._bump = getattr(self, "_bump", 0) + 1

    def deny(self, code, cmd, lock="sesame5_b", now=NOW):
        with self.assertRaises(authz.Denied) as cm:
            self.az.authorize(lock, cmd, now=now)
        self.assertEqual(cm.exception.code, code)

    # --- 署名 ---
    def test_valid_signature_passes(self):
        user = self.az.authorize("sesame5_b", make_cmd("alice", key=self.alice), now=NOW)
        self.assertEqual(user["history_tag"], "MQTT:alice")

    def test_tampered_field_fails(self):
        cmd = make_cmd("alice", action="lock", key=self.alice)
        cmd["action"] = "unlock"
        self.deny("BAD_SIG", cmd)

    def test_signature_by_other_user_fails(self):
        cmd = make_cmd("alice", key=self.bob)       # bob の鍵で alice を名乗る
        self.deny("BAD_SIG", cmd)

    def test_unknown_user_same_code_as_bad_sig(self):
        self.deny("BAD_SIG", make_cmd("mallory", key=self.alice))

    def test_canonical_is_key_sorted_and_compact(self):
        cmd = {"v": 1, "req_id": "r", "user": "u", "lock": "l", "action": "lock", "ts": 1, "nonce": "n", "sig": "x"}
        self.assertEqual(authz.canonical_bytes(cmd),
                         b'{"action":"lock","lock":"l","nonce":"n","req_id":"r","ts":1,"user":"u","v":1}')

    # --- 再送・時刻 ---
    def test_replay_same_nonce_rejected(self):
        cmd = make_cmd("alice", key=self.alice)
        self.az.authorize("sesame5_b", cmd, now=NOW)
        self.deny("REPLAY", cmd)

    def test_expired_timestamp(self):
        self.deny("EXPIRED", make_cmd("alice", ts=NOW - 120, key=self.alice))
        self.deny("EXPIRED", make_cmd("alice", ts=NOW + 120, key=self.alice))

    def test_lock_mismatch_with_topic(self):
        self.deny("BAD_REQUEST", make_cmd("alice", lock="sesame5_t", key=self.alice), lock="sesame5_b")

    # --- 権限 ---
    def test_grant_lock_not_allowed(self):
        self.deny("FORBIDDEN", make_cmd("bob", lock="sesame5_t", key=self.bob), lock="sesame5_t")

    def test_schedule_inside_window(self):
        self.az.authorize("sesame5_b", make_cmd("bob", key=self.bob), now=NOW)   # 木 17:53 JST

    def test_schedule_outside_hours(self):
        late = NOW + 3600                                                      # 木 18:53 JST
        self.deny("FORBIDDEN", make_cmd("bob", ts=late, key=self.bob), now=late)

    def test_schedule_wrong_day(self):
        fri = NOW + 86400                                                      # 金 17:53 JST
        self.deny("FORBIDDEN", make_cmd("bob", ts=fri, key=self.bob), now=fri)

    def test_valid_until_passed(self):
        self.cfg["users"]["bob"]["grants"][0]["valid_until"] = "2020-01-01T00:00:00+09:00"
        self.write(self.cfg)
        self.deny("FORBIDDEN", make_cmd("bob", key=self.bob))

    def test_disabled_user(self):
        self.cfg["users"]["alice"]["enabled"] = False
        self.write(self.cfg)
        self.deny("FORBIDDEN", make_cmd("alice", key=self.alice))

    def test_global_disabled(self):
        self.cfg["enabled"] = False
        self.write(self.cfg)
        self.deny("DISABLED", make_cmd("alice", key=self.alice))

    def test_allowed_actions_phase_gate(self):
        self.cfg["allowed_actions"] = ["lock"]
        self.write(self.cfg)
        self.deny("FORBIDDEN", make_cmd("alice", action="unlock", key=self.alice))
        self.az.authorize("sesame5_b", make_cmd("alice", action="lock", key=self.alice), now=NOW)

    # --- レート制限 ---
    def test_unlock_rate_limit_per_minute(self):
        self.az.authorize("sesame5_b", make_cmd("alice", action="unlock", key=self.alice), now=NOW)
        self.az.authorize("sesame5_b", make_cmd("alice", action="unlock", key=self.alice), now=NOW + 1)
        self.deny("RATE_LIMIT", make_cmd("alice", action="unlock", ts=NOW + 2, key=self.alice), now=NOW + 2)

    # --- フェイルクローズ ---
    def test_broken_file_denies_everything(self):
        with open(self.path, "w") as f:
            f.write("{ broken json")
        os.utime(self.path, (NOW + 50, NOW + 50))
        self.deny("DISABLED", make_cmd("alice", key=self.alice))

    def test_missing_file_denies_everything(self):
        os.remove(self.path)
        self.deny("DISABLED", make_cmd("alice", key=self.alice))

    def test_hot_reload_picks_up_new_user(self):
        carol_pem, carol_pub = authz.generate_keypair()
        self.deny("BAD_SIG", make_cmd("carol", key=ECC.import_key(carol_pem)))
        self.cfg["users"]["carol"] = {"enabled": True, "pubkey": carol_pub,
                                      "grants": [{"locks": ["sesame5_b"], "actions": ["lock"]}]}
        self.write(self.cfg)
        self.az.authorize("sesame5_b", make_cmd("carol", key=ECC.import_key(carol_pem)), now=NOW)


if __name__ == "__main__":
    unittest.main()
