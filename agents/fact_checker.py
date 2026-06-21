import os
import logging

import anthropic

logger = logging.getLogger(__name__)


class FactChecker:
    def __init__(self):
        self.claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def check(self, script, research):
        claims_text = "\n".join([
            f"- {c['claim']} (source: {c['source_url']})"
            for c in research["claims"]
        ])

        response = self.claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": (
                    f"You are a fact-checker for a news podcast.\n\n"
                    f"VERIFIED CLAIMS (ground truth):\n{claims_text}\n\n"
                    f"SCRIPT TO CHECK:\n{script}\n\n"
                    f"Review every factual statement in the script.\n"
                    f"For any claim NOT supported by the verified list above:\n"
                    f"  - Remove it, or replace it with a supported version\n"
                    f"If the script is accurate, return it unchanged.\n\n"
                    f"Return ONLY the corrected script text. No explanations, no headers, no commentary."
                )
            }]
        )

        verified = response.content[0].text.strip()
        logger.info("Fact check complete")
        return verified
