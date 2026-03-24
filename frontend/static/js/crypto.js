/**
 * All_Chat — Client-Side Cryptography
 * X25519 ECDH key exchange + AES-256-GCM message encryption.
 * All crypto happens here — the server NEVER sees plaintext.
 *
 * Key storage:
 *   - Public key: registered with server on login
 *   - Private key: stored in IndexedDB (never leaves the browser)
 *
 * Message flow:
 *   Send:    ECDH(sender_ephemeral_priv, recipient_pub) → shared_secret
 *            AES-GCM(shared_secret, plaintext) → {ciphertext, nonce}
 *            POST {ephemeral_pub_b64, aes_ciphertext_b64, aes_nonce_b64}
 *
 *   Receive: ECDH(our_priv, sender_ephemeral_pub) → shared_secret
 *            AES-GCM-decrypt(shared_secret, ciphertext, nonce) → plaintext
 */

const CryptoE2E = (() => {
  const DB_NAME    = 'allchat_keys';
  const STORE_NAME = 'keypairs';
  const KEY_NAME   = 'identity';

  // ── IndexedDB ───────────────────────────────────────────────────

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = e => {
        e.target.result.createObjectStore(STORE_NAME);
      };
      req.onsuccess = e => resolve(e.target.result);
      req.onerror   = e => reject(e.target.error);
    });
  }

  async function storeKey(keyPair) {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx    = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      store.put(keyPair, KEY_NAME);
      tx.oncomplete = resolve;
      tx.onerror    = e => reject(e.target.error);
    });
  }

  async function loadKey() {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx    = db.transaction(STORE_NAME, 'readonly');
      const store = tx.objectStore(STORE_NAME);
      const req   = store.get(KEY_NAME);
      req.onsuccess = e => resolve(e.target.result || null);
      req.onerror   = e => reject(e.target.error);
    });
  }

  // ── Key Generation & Registration ───────────────────────────────

  async function generateAndStoreKeyPair() {
    const keyPair = await crypto.subtle.generateKey(
      { name: 'ECDH', namedCurve: 'P-256' },
      true, // extractable (for export)
      ['deriveKey', 'deriveBits'],
    );
    await storeKey(keyPair);
    return keyPair;
  }

  async function getOrCreateKeyPair() {
    let kp = await loadKey();
    if (!kp) kp = await generateAndStoreKeyPair();
    return kp;
  }

  async function exportPublicKeyB64(keyPair) {
    const raw = await crypto.subtle.exportKey('raw', keyPair.publicKey);
    return btoa(String.fromCharCode(...new Uint8Array(raw)));
  }

  async function registerPublicKey() {
    const kp  = await getOrCreateKeyPair();
    const b64 = await exportPublicKeyB64(kp);
    await API.post('/users/me/public-key', { public_key: b64 });
    return b64;
  }

  // ── Encryption (Send) ────────────────────────────────────────────

  async function encryptMessage(plaintext, recipientPublicKeyB64) {
    // Decode recipient public key
    const recipientRaw = Uint8Array.from(atob(recipientPublicKeyB64), c => c.charCodeAt(0));
    const recipientKey = await crypto.subtle.importKey(
      'raw', recipientRaw, { name: 'ECDH', namedCurve: 'P-256' }, false, []
    );

    // Generate ephemeral keypair for this message
    const ephemeral = await crypto.subtle.generateKey(
      { name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveKey', 'deriveBits']
    );

    // Derive shared secret
    const sharedKey = await crypto.subtle.deriveKey(
      { name: 'ECDH', public: recipientKey },
      ephemeral.privateKey,
      { name: 'AES-GCM', length: 256 },
      false,
      ['encrypt']
    );

    // Encrypt message
    const nonce = crypto.getRandomValues(new Uint8Array(12));
    const enc   = new TextEncoder();
    const ct    = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv: nonce },
      sharedKey,
      enc.encode(plaintext)
    );

    // Export ephemeral public key (acts as "kyber_ciphertext" in our schema)
    const ephPubRaw = await crypto.subtle.exportKey('raw', ephemeral.publicKey);

    return {
      kyber_ciphertext: toB64(new Uint8Array(ephPubRaw)),
      aes_ciphertext:   toB64(new Uint8Array(ct)),
      aes_nonce:        toB64(nonce),
      crypto_version:   'x25519-p256-aes256gcm',
    };
  }

  // ── Decryption (Receive) ──────────────────────────────────────────

  async function decryptMessage(kyberCiphertextB64, aesCiphertextB64, aesNonceB64) {
    const kp = await getOrCreateKeyPair();

    // Import sender's ephemeral public key
    const ephPubRaw = fromB64(kyberCiphertextB64);
    const senderEphKey = await crypto.subtle.importKey(
      'raw', ephPubRaw, { name: 'ECDH', namedCurve: 'P-256' }, false, []
    );

    // Derive shared secret using our private key
    const sharedKey = await crypto.subtle.deriveKey(
      { name: 'ECDH', public: senderEphKey },
      kp.privateKey,
      { name: 'AES-GCM', length: 256 },
      false,
      ['decrypt']
    );

    // Decrypt
    const ct    = fromB64(aesCiphertextB64);
    const nonce = fromB64(aesNonceB64);
    const plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: nonce },
      sharedKey,
      ct
    );

    return new TextDecoder().decode(plain);
  }

  // ── Helpers ───────────────────────────────────────────────────────

  function toB64(u8) { return btoa(String.fromCharCode(...u8)); }
  function fromB64(b64) { return Uint8Array.from(atob(b64), c => c.charCodeAt(0)); }

  return {
    getOrCreateKeyPair,
    exportPublicKeyB64,
    registerPublicKey,
    encryptMessage,
    decryptMessage,
  };
})();
