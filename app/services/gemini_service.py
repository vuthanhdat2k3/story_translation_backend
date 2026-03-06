"""Gemini AI service for Chinese-to-Vietnamese translation."""

import time
import logging
import google.generativeai as genai
from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
genai.configure(api_key=settings.GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-2.5-flash-lite")

import json

def translate_chunk(text: str, title: str | None = None, character_dict: dict[str, str] | None = None) -> dict:
    """
    Translate a chunk of Chinese text to Vietnamese using Gemini.
    Returns a dict with:
      - 'translation': the translated text
      - 'translated_title': the translated title (if title was provided)
      - 'new_characters': a dict of Chinese->Vietnamese mapped names newly found.
    """
    name_dict_section = ""
    if character_dict:
        name_entries = "\n".join(
            f"  {cn} = {vi}" for cn, vi in character_dict.items()
        )
        name_dict_section = f"""
Existing Dictionary (DO NOT include these in new_characters):
{name_entries}
"""

    title_prompt = f"Title to translate:\n{title}\n\n" if title else ""
    title_schema = '\n  "translated_title": "<translated Vietnamese title>",' if title else ""

    prompt = f"""You are a professional Chinese-Vietnamese novel translator.

Rules:
- Translate the following Chinese text to natural, fluent Vietnamese.
- Keep character names consistent. Use the Existing Dictionary if provided.
- Maintain the tone and style of web novels (wuxia, xianxia, etc).
- Do NOT summarize or skip any content.
- Identify any NEW character names in the text that are NOT in the Existing Dictionary. Ensure these are human names or distinct entities. Output their Chinese names and Vietnamese phonetic translations.

Output MUST be a valid JSON object matching this schema:
{{{title_schema}
  "translation": "<translated Vietnamese text>",
  "new_characters": {{
    "ChineseName1": "VietnameseName1"
  }}
}}
{name_dict_section}
{title_prompt}Chinese text:
{text}"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                    max_output_tokens=8192,
                )
            )
            if response.text:
                try:
                    data = json.loads(response.text.strip())
                    return data
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON from Gemini (attempt {attempt + 1}): {e}\nResponse: {response.text}")
                    # Attempt to salvage a truncated response by closing open structures
                    try:
                        repaired = response.text.strip()
                        if not repaired.endswith("}"):
                            repaired = repaired.rstrip(",\n ") + '\n  "new_characters": {}\n}'
                        data = json.loads(repaired)
                        logger.info(f"Successfully repaired truncated JSON on attempt {attempt + 1}")
                        return data
                    except json.JSONDecodeError:
                        pass
            else:
                logger.warning(f"Empty response from Gemini (attempt {attempt + 1})")
        except Exception as e:
            logger.error(f"Gemini API error (attempt {attempt + 1}): {e}")

        if attempt < max_retries - 1:
            wait_time = 2 ** attempt * 5
            time.sleep(wait_time)

    return {"translation": text, "new_characters": {}}



def extract_character_names(text: str) -> list[dict[str, str]]:
    """
    Use Gemini to extract character names from Chinese text.
    
    Returns a list of dicts with cn_name and vi_name.
    """
    prompt = f"""Analyze the following Chinese novel text and extract all character names (人名).
For each character name, provide the Vietnamese translation/phonetic equivalent.

Output format (one per line, no extra text):
Chinese_Name = Vietnamese_Name

Example:
张三 = Trương Tam
李四 = Lý Tứ

Chinese text:
{text[:3000]}"""

    try:
        response = model.generate_content(prompt)
        if not response.text:
            return []

        names = []
        for line in response.text.strip().split("\n"):
            line = line.strip()
            if "=" in line:
                parts = line.split("=", 1)
                if len(parts) == 2:
                    cn = parts[0].strip()
                    vi = parts[1].strip()
                    if cn and vi:
                        names.append({"cn_name": cn, "vi_name": vi})
        return names
    except Exception as e:
        logger.error(f"Error extracting character names: {e}")
        return []
