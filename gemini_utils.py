import google.generativeai as genai
import os
import json

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel("gemini-1.5-flash")

CATEGORIES = [
    "Automobile",
    "Bike Repair",
    "Education",
    "Home Services",
    "Electronics",
    "Other",
]


async def parse_intent(problem: str) -> dict:
    prompt = f"""
You are Servly AI's intent parser.
Analyze the user's problem and return JSON only.

Problem: "{problem}"

Return ONLY this JSON (no markdown, no explanation):
{{
  "category": "",
  "urgency": "low|medium|high",
  "summary": "<15 word max summary>",
  "keywords": ["keyword1", "keyword2"]
}}

Choose category from: {CATEGORIES}
"""
    response = model.generate_content(prompt)
    text = response.text.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    return json.loads(text.strip())
