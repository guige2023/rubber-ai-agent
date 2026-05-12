from __future__ import annotations

from datetime import date, datetime

from jsonrpcserver import Success, method


def format_optional_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


@method
async def list_skills(context):
    if context and hasattr(context, "runtime"):
        skills = sorted(context.runtime.skill_manager.skills.values(), key=lambda skill: skill.name.lower())
        skills = sorted(
            skills,
            key=lambda skill: format_optional_date(getattr(skill, "updated", None)) or "",
            reverse=True,
        )
        return Success([
            {
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "author": skill.author,
                "created": format_optional_date(getattr(skill, "created", None)),
                "updated": format_optional_date(getattr(skill, "updated", None)),
            }
            for skill in skills
        ])

    return Success([])
