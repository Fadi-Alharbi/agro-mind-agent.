import json
import re
import time
from deep_translator import GoogleTranslator

INPUT_FILE  = r'c:\Users\fshos\OneDrive\my projects\tra\2\2.1\cat1_usage_product_real.jsonl'
OUTPUT_FILE = r'c:\Users\fshos\OneDrive\my projects\tra\2\2.1\cat1_usage_product_real_EN.jsonl'

translator = GoogleTranslator(source='zh-CN', target='en')

def has_chinese(text):
    return bool(re.search(r'[\u4e00-\u9fff]', text)) if isinstance(text, str) else False

def translate(text):
    if not isinstance(text, str) or not text.strip() or not has_chinese(text):
        return text
    MAX = 4500
    if len(text) <= MAX:
        try:
            result = translator.translate(text)
            time.sleep(0.2)
            return result or text
        except Exception as e:
            print(f"  [ERROR] {e}")
            return text
    # Split long texts by paragraph
    parts = text.split('\n\n')
    translated = []
    for part in parts:
        if not has_chinese(part):
            translated.append(part)
            continue
        if len(part) <= MAX:
            try:
                r = translator.translate(part)
                translated.append(r or part)
                time.sleep(0.2)
            except Exception as e:
                print(f"  [ERROR paragraph] {e}")
                translated.append(part)
        else:
            # split by single newline
            lines = part.split('\n')
            chunk, result_lines = '', []
            for ln in lines:
                if len(chunk) + len(ln) + 1 < MAX:
                    chunk += ln + '\n'
                else:
                    if chunk:
                        try:
                            r = translator.translate(chunk.strip())
                            result_lines.append(r or chunk)
                            time.sleep(0.2)
                        except:
                            result_lines.append(chunk)
                    chunk = ln + '\n'
            if chunk:
                try:
                    r = translator.translate(chunk.strip())
                    result_lines.append(r or chunk)
                    time.sleep(0.2)
                except:
                    result_lines.append(chunk)
            translated.append('\n'.join(result_lines))
    return '\n\n'.join(translated)

with open(INPUT_FILE, encoding='utf-8') as f:
    lines = [l.strip() for l in f if l.strip()]

print(f"Translating {len(lines)} conversations...")
print("=" * 60)

output_lines = []
for i, line in enumerate(lines, 1):
    record = json.loads(line)
    messages = record.get('messages', [])
    new_messages = []
    for msg in messages:
        role = msg.get('role', '')
        content = msg.get('content', '')
        translated_content = translate(content)
        if translated_content != content:
            print(f"  [{i}] {role}: {repr(content[:60])} → {repr(translated_content[:60])}")
        new_messages.append({'role': role, 'content': translated_content})
    record['messages'] = new_messages
    output_lines.append(json.dumps(record, ensure_ascii=False))
    print(f"[{i}/{len(lines)}] Done conversation {i}")

with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write('\n'.join(output_lines) + '\n')

print()
print("=" * 60)
print(f"DONE! Translated {len(output_lines)} conversations.")
print(f"Output: {OUTPUT_FILE}")
