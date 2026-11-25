from typing import Any

from sqlalchemy.orm import Session

from .. import models as M


def audit(db: Session, actor: str, action: str, entity: str, entity_id: str | None = None,
          before: Any = None, after: Any = None) -> None:
    db.add(M.AuditEvent(actor=actor, action=action, entity=entity, entity_id=entity_id,
                        before=before, after=after))


def notify(db: Session, message: str, audience: str = "ALL", roster_id: str | None = None,
           employee_id: str | None = None) -> None:
    db.add(M.Notification(message=message, audience=audience, roster_id=roster_id, employee_id=employee_id))
