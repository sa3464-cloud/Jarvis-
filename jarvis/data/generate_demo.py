"""Generate stable, clearly fictional JARVIS fixtures. Run from any working directory."""
from pathlib import Path
import hashlib
import random

ROOT = Path(__file__).resolve().parent / "demo"
RANDOM_SEED = 202607
_rng = random.Random(RANDOM_SEED)  # fixed seed; fixture values are intentionally fixed
FILES = {
    "course_circuits.md": """---\ntype: course\ntitle: EE 101: Circuits (fictional)\n---\n# EE 101: Circuits (fictional)\nDemo course description for testing the JARVIS index.\nSee [[Ohm's law notes]] and [[Lab 1: resistor study]].\n""",
    "note_ohms_law.md": """---\ntype: note\ntitle: Ohm's law notes\n---\n# Ohm's law notes\nFor this fictional example, Ohm's law is represented as V = I R.\nSee [[EE 101: Circuits (fictional)]] and [[Lab 1: resistor study]].\n""",
    "assignment_lab1.md": """---\ntype: assignment\ntitle: Lab 1: resistor study\n---\n# Lab 1: resistor study\nFictional task: record voltage and current for three sample resistors.\nDue date: 2030-01-15 (demo reference date: 2030-01-01).\nSee [[EE 101: Circuits (fictional)]] and [[Ohm's law notes]].\n""",
    "project_portfolio.md": """---\ntype: project\ntitle: Portfolio prototype\n---\n# Portfolio prototype\nFictional project: build a simple portfolio page and document design decisions.\nSee [[Skills for internships]].\n""",
    "career_internships.md": """---\ntype: career\ntitle: Skills for internships\n---\n# Skills for internships\nFictional note: describe one project, the tools used, and what you learned.\nSee [[Portfolio prototype]].\n""",
    "exam_review.md": """---\ntype: exam\ntitle: Circuits review (fictional)\n---\n# Circuits review (fictional)\nFictional exam fixture. Review [[Ohm's law notes]] and [[EE 101: Circuits (fictional)]].\n""",
    "calendar_sample.md": """---\ntype: calendar\ntitle: Demo calendar events\n---\n# Demo calendar events\nSample only; these events are not connected to a real calendar.\n2030-01-08 — Fictional study block (estimate, not a real commitment).\n""",
    "message_sample.md": """---\ntype: message\ntitle: Sample message (fictional)\n---\n# Sample message (fictional)\nClearly fictional sample message. No inbox was accessed.\n""",
}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    for name in sorted(FILES):
        content = FILES[name]
        stable_id = hashlib.sha256(f"{RANDOM_SEED}:{name}".encode("utf-8")).hexdigest()[:12]
        content = content.replace("# ", f"<!-- fixture:{stable_id} -->\n# ", 1)
        (ROOT / name).write_text(content, encoding="utf-8", newline="\n")
    print(f"Generated {len(FILES)} deterministic fictional files in {ROOT}")


if __name__ == "__main__":
    main()
