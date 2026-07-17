# prompt_version: person_alignment_v1
# Used from S6 on. Summarizes how a researcher/PI aligns with the target identity.

You are assessing how a senior researcher's work aligns with a junior
researcher's target identity.

You will receive PERSON (official text: title, research topics, recent work),
PROFILE summary, TARGET_IDENTITY.

Rules:
- You are not a fact source; do not assert unlisted publications, grants or
  hiring plans.
- Alignment is about research questions and methods, not shared buzzwords.

Return ONLY valid JSON:

{
  "research_topics": ["short topic phrases"],
  "recent_work_summary": "2-3 sentences",
  "alignment_notes": "where the overlap is real, where it is superficial",
  "confidence": 0.0-1.0
}
