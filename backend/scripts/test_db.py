from __future__ import annotations

from database.session import SessionLocal
from database.models.program import Program


def main() -> None:
    with SessionLocal() as db:
        program = Program(name="Test Program", platform="local", status="active")
        db.add(program)
        db.commit()
        db.refresh(program)

        fetched = db.get(Program, program.id)
        if not fetched:
            raise RuntimeError("Failed to fetch created program")

        print(
            "Inserted program:",
            {
                "id": str(fetched.id),
                "name": fetched.name,
                "platform": fetched.platform,
                "status": fetched.status,
                "created_at": fetched.created_at,
            },
        )


if __name__ == "__main__":
    main()
