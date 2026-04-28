import os
import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

_llm = None

def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            google_api_key=os.environ["GEMINI_API_KEY"],
            temperature=0.1,
        )
    return _llm

CATEGORIES = [
    "Automobile",
    "Bike Repair",
    "Education",
    "Home Services",
    "Electronics",
    "Other",
]


async def parse_intent(problem: str) -> dict:
    prompt = f"""You are Servly AI's intent parser.
Analyze the user's problem and return JSON only.

Problem: "{problem}"

Return ONLY this JSON (no markdown, no explanation):
{{
  "category": "",
  "urgency": "low|medium|high",
  "summary": "<15 word max summary>",
  "keywords": ["keyword1", "keyword2"]
}}

Choose category from: {CATEGORIES}"""

    llm = _get_llm()
    response = llm.invoke([HumanMessage(content=prompt)])
    text = response.content.strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    return json.loads(text.strip())
