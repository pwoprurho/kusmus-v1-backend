import os
import secrets
from eth_account import Account
import bitcoin
import json
from cryptography.fernet import Fernet


def _get_wallet_cipher():
    """
    Returns a Fernet cipher for wallet key encryption.
    Uses the same ENCRYPTION_KEY as chat encryption.
    Fails closed if the key is missing.
    """
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("CRITICAL: ENCRYPTION_KEY not set. Cannot encrypt/decrypt wallet keys.")
    return Fernet(key.encode())


class Wallet:
    def __init__(self, user_id):
        self.user_id = user_id
        self.eth_address = None
        self._eth_private_key_encrypted = None
        self.btc_address = None
        self._btc_private_key_encrypted = None

        # Try to load existing wallet from disk first
        loaded = self._load_from_disk()
        if not loaded:
            self._create_wallets()
            self._save_to_disk()

    def _create_wallets(self):
        """Generate new wallet keypairs and encrypt private keys immediately."""
        cipher = _get_wallet_cipher()

        # Ethereum wallet
        acct = Account.create(secrets.token_hex(32))
        self.eth_address = acct.address
        self._eth_private_key_encrypted = cipher.encrypt(acct.key.hex().encode()).decode()

        # Bitcoin wallet
        key = bitcoin.random_key()
        self._btc_private_key_encrypted = cipher.encrypt(key.encode()).decode()
        self.btc_address = bitcoin.privtopub(key)

    @property
    def eth_private_key(self):
        """Decrypt ETH private key on demand — never stored in plaintext."""
        if not self._eth_private_key_encrypted:
            return None
        cipher = _get_wallet_cipher()
        return cipher.decrypt(self._eth_private_key_encrypted.encode()).decode()

    @property
    def btc_private_key(self):
        """Decrypt BTC private key on demand — never stored in plaintext."""
        if not self._btc_private_key_encrypted:
            return None
        cipher = _get_wallet_cipher()
        return cipher.decrypt(self._btc_private_key_encrypted.encode()).decode()

    def get_wallet_info(self):
        """Returns only public addresses — NEVER private keys."""
        return {
            'eth_address': self.eth_address,
            'btc_address': self.btc_address
        }

    def _save_to_disk(self):
        """Persist wallet with encrypted private keys."""
        os.makedirs('data', exist_ok=True)
        wallet_path = os.path.join('data', f'wallet_{self.user_id}.json')
        data = {
            'eth_address': self.eth_address,
            'eth_private_key_enc': self._eth_private_key_encrypted,
            'btc_address': self.btc_address,
            'btc_private_key_enc': self._btc_private_key_encrypted
        }
        with open(wallet_path, 'w') as f:
            json.dump(data, f)

    def _load_from_disk(self) -> bool:
        """Load wallet from encrypted file. Returns False if not found."""
        wallet_path = os.path.join('data', f'wallet_{self.user_id}.json')
        if not os.path.exists(wallet_path):
            return False
        try:
            with open(wallet_path, 'r') as f:
                data = json.load(f)

            self.eth_address = data.get('eth_address')
            self.btc_address = data.get('btc_address')

            # Support both new encrypted format and legacy plaintext migration
            if data.get('eth_private_key_enc'):
                self._eth_private_key_encrypted = data['eth_private_key_enc']
            elif data.get('eth_private_key'):
                # Migrate legacy plaintext key → encrypt and re-save
                cipher = _get_wallet_cipher()
                self._eth_private_key_encrypted = cipher.encrypt(data['eth_private_key'].encode()).decode()

            if data.get('btc_private_key_enc'):
                self._btc_private_key_encrypted = data['btc_private_key_enc']
            elif data.get('btc_private_key'):
                cipher = _get_wallet_cipher()
                self._btc_private_key_encrypted = cipher.encrypt(data['btc_private_key'].encode()).decode()

            # Re-save if we migrated any legacy keys
            if data.get('eth_private_key') or data.get('btc_private_key'):
                self._save_to_disk()

            return True
        except Exception as e:
            print(f"Wallet Load Error for {self.user_id}: {e}")
            return False

    @staticmethod
    def get_wallet(user_id):
        """Load an existing wallet by user_id. Returns None if not found."""
        wallet_path = os.path.join('data', f'wallet_{user_id}.json')
        if not os.path.exists(wallet_path):
            return None
        return Wallet(user_id)
