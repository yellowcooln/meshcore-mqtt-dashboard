#!/usr/bin/env node

const { MeshCoreKeyStore } = require('@michaelhart/meshcore-decoder/dist/crypto/key-manager.js');
const { GroupTextPayloadDecoder } = require('@michaelhart/meshcore-decoder/dist/decoder/payload-decoders/group-text.js');

function normalizeRawHex(value) {
  return String(value || '').trim().toUpperCase();
}

function extractGroupTextPayload(rawHex) {
  if (!/^[0-9A-F]+$/.test(rawHex) || rawHex.length < 6 || rawHex.length % 2 !== 0) {
    return null;
  }
  const raw = Buffer.from(rawHex, 'hex');
  if (raw.length < 3) {
    return null;
  }
  const pathLen = raw[1];
  const pathHashSize = ((pathLen >> 6) & 0x03) + 1;
  const pathHashCount = pathLen & 0x3F;
  const payloadOffset = 2 + (pathHashSize * pathHashCount);
  if (payloadOffset >= raw.length) {
    return null;
  }
  return new Uint8Array(raw.subarray(payloadOffset));
}

function decodePacket(rawHex, keyStore) {
  try {
    const payload = extractGroupTextPayload(rawHex);
    if (!payload) {
      return null;
    }
    const decoded = GroupTextPayloadDecoder.decode(payload, { keyStore });
    const decrypted = decoded && decoded.decrypted;
    if (!decrypted || typeof decrypted.message !== 'string') {
      return null;
    }
    const message = decrypted.message.trim();
    if (!message) {
      return null;
    }
    const sender = typeof decrypted.sender === 'string' && decrypted.sender.trim()
      ? decrypted.sender.trim()
      : '';
    return {
      sender_timestamp: Number(decrypted.timestamp || 0),
      flags: Number(decrypted.flags || 0),
      text: sender ? `${sender}: ${message}` : message,
    };
  } catch (_error) {
    return null;
  }
}

function main() {
  let input = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk) => {
    input += chunk;
  });
  process.stdin.on('end', () => {
    try {
      const payload = JSON.parse(input || '{}');
      const channelKey = String(payload.channelKey || '').trim().toLowerCase();
      const rawHexes = Array.isArray(payload.rawHexes) ? payload.rawHexes : [];
      if (!/^[0-9a-f]{32}$/.test(channelKey)) {
        process.stdout.write(JSON.stringify({ results: {} }));
        return;
      }
      const keyStore = new MeshCoreKeyStore({ channelSecrets: [channelKey] });
      const results = {};
      for (const value of rawHexes) {
        const rawHex = normalizeRawHex(value);
        if (!rawHex) {
          continue;
        }
        const decoded = decodePacket(rawHex, keyStore);
        if (decoded) {
          results[rawHex] = decoded;
        }
      }
      process.stdout.write(JSON.stringify({ results }));
    } catch (error) {
      process.stderr.write(String(error && error.message ? error.message : error));
      process.exit(1);
    }
  });
}

main();
