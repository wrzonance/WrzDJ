/** Test fixtures for building the null-terminated UTF-16 Serato chunk format. */
export function encodeNullTerminatedUtf16BE(value: string): Buffer {
  const buffer = Buffer.alloc((value.length + 1) * 2);
  for (let index = 0; index < value.length; index += 1) {
    buffer.writeUInt16BE(value.charCodeAt(index), index * 2);
  }
  return buffer;
}

export function buildSeratoField(fieldId: number, data: Buffer): Buffer {
  const header = Buffer.alloc(8);
  header.writeUInt32BE(fieldId, 0);
  header.writeUInt32BE(data.length, 4);
  return Buffer.concat([header, data]);
}

export function buildSeratoTextField(fieldId: number, text: string): Buffer {
  return buildSeratoField(fieldId, encodeNullTerminatedUtf16BE(text));
}

export function buildSeratoU32Field(fieldId: number, value: number): Buffer {
  const data = Buffer.alloc(4);
  data.writeUInt32BE(value, 0);
  return buildSeratoField(fieldId, data);
}

export function wrapSeratoChunk(tag: string, content: Buffer): Buffer {
  const header = Buffer.alloc(8);
  header.write(tag, 0, 4, "ascii");
  header.writeUInt32BE(content.length, 4);
  return Buffer.concat([header, content]);
}

export function buildSeratoOentChunk(fields: Buffer[]): Buffer {
  return wrapSeratoChunk("oent", wrapSeratoChunk("adat", Buffer.concat(fields)));
}
