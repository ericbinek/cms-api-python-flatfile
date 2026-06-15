import json
import time
from datetime import datetime, timezone

# Compiled access policy for this target, derived from the project-wide access/
# authority (roles.json, field-access.json, workflow.json). Pure data plus pure
# helpers — no IO, no request handling. The router and server enforce it.

_POLICY = json.loads(
    r"""{
      "operations": [
        "read",
        "create",
        "update",
        "delete"
      ],
      "roles": {
        "admin": {
          "description": "Full access to every entity plus account management.",
          "matrix": {
            "*": [
              "read",
              "create",
              "update",
              "delete"
            ]
          },
          "accountManagement": true
        },
        "editor": {
          "description": "Full CRUD on every entity. Drives the publication workflow.",
          "matrix": {
            "*": [
              "read",
              "create",
              "update",
              "delete"
            ]
          }
        },
        "author": {
          "description": "Reads and creates every entity, but updates and deletes only own records.",
          "matrix": {
            "*": [
              "read",
              "create",
              "update",
              "delete"
            ]
          },
          "ownership": {
            "scope": "own",
            "operations": [
              "update",
              "delete"
            ],
            "field": "createdBy"
          }
        },
        "viewer": {
          "description": "Authenticated read only across every entity, including non public status.",
          "matrix": {
            "*": [
              "read"
            ]
          }
        },
        "anonymous": {
          "description": "Unauthenticated read, no session. Restricted to publicly visible records via the read visibility rule.",
          "matrix": {
            "*": [
              "read"
            ]
          },
          "read": {
            "visibility": "public"
          }
        }
      },
      "visibility": {
        "description": "Read visibility scopes a role read rule can reference. \"all\" returns every record, so reads stay backward compatible with the current auth free API. \"public\" restricts status bearing entities to their public states defined in access/workflow.json, and where a datePublished property exists it must be reached; entities without a status enum stay fully readable either way. Which scope the anonymous role ships with at rollout is the open decision for the API auth block, see docs/auth/implementation-plan.md.",
        "scopes": [
          "all",
          "public"
        ]
      },
      "fieldGroups": {
        "system": [
          "id",
          "dateCreated",
          "dateModified"
        ],
        "internal": [
          "createdBy"
        ]
      },
      "fieldRules": {
        "*": {
          "read": {
            "deny": [
              "@internal"
            ]
          },
          "write": {
            "deny": [
              "@system",
              "@internal"
            ]
          }
        }
      },
      "workflow": {
        "BlogPosting": {
          "statusProperty": "creativeWorkStatus",
          "initial": "Draft",
          "public": [
            "Published"
          ],
          "transitions": [
            {
              "from": "Draft",
              "to": "Pending",
              "roles": [
                "author",
                "editor",
                "admin"
              ]
            },
            {
              "from": "Pending",
              "to": "Draft",
              "roles": [
                "editor",
                "admin"
              ]
            },
            {
              "from": "Pending",
              "to": "Published",
              "roles": [
                "editor",
                "admin"
              ]
            },
            {
              "from": "Published",
              "to": "Archived",
              "roles": [
                "editor",
                "admin"
              ]
            },
            {
              "from": "Archived",
              "to": "Published",
              "roles": [
                "editor",
                "admin"
              ]
            }
          ],
          "hasPublishDate": true
        },
        "WebPage": {
          "statusProperty": "creativeWorkStatus",
          "initial": "Draft",
          "public": [
            "Published"
          ],
          "transitions": [
            {
              "from": "Draft",
              "to": "Pending",
              "roles": [
                "author",
                "editor",
                "admin"
              ]
            },
            {
              "from": "Pending",
              "to": "Draft",
              "roles": [
                "editor",
                "admin"
              ]
            },
            {
              "from": "Pending",
              "to": "Published",
              "roles": [
                "editor",
                "admin"
              ]
            },
            {
              "from": "Published",
              "to": "Archived",
              "roles": [
                "editor",
                "admin"
              ]
            },
            {
              "from": "Archived",
              "to": "Published",
              "roles": [
                "editor",
                "admin"
              ]
            }
          ],
          "hasPublishDate": true
        },
        "Comment": {
          "statusProperty": "creativeWorkStatus",
          "initial": "Pending",
          "public": [
            "Approved"
          ],
          "transitions": [
            {
              "from": "Pending",
              "to": "Approved",
              "roles": [
                "editor",
                "admin"
              ]
            },
            {
              "from": "Pending",
              "to": "Spam",
              "roles": [
                "editor",
                "admin"
              ]
            },
            {
              "from": "Approved",
              "to": "Spam",
              "roles": [
                "editor",
                "admin"
              ]
            },
            {
              "from": "Approved",
              "to": "Trash",
              "roles": [
                "editor",
                "admin"
              ]
            },
            {
              "from": "Spam",
              "to": "Trash",
              "roles": [
                "editor",
                "admin"
              ]
            }
          ],
          "hasPublishDate": false
        }
      }
    }"""
)

_ROLES = _POLICY["roles"]
_WORKFLOW = _POLICY["workflow"]
_SYSTEM_FIELDS = set(_POLICY["fieldGroups"]["system"])
_INTERNAL_FIELDS = set(_POLICY["fieldGroups"]["internal"])
_FIELD_RULES = _POLICY["fieldRules"]


def _deny_set(role, mode):
    # Resolves a role's field rule for a mode (read/write) into a concrete deny
    # set, expanding the group references @system and @internal. A per-role rule
    # wins over the "*" default; "deny" wins; an absent rule denies nothing.
    by_role = _FIELD_RULES.get(role, {}).get(mode)
    by_default = _FIELD_RULES.get("*", {}).get(mode)
    rule = by_role or by_default or {}
    deny = set()
    for entry in rule.get("deny", []):
        if entry == "@system":
            deny.update(_SYSTEM_FIELDS)
        elif entry == "@internal":
            deny.update(_INTERNAL_FIELDS)
        else:
            deny.add(entry)
    return deny


# The fields no client may ever write (system + internal), i.e. the default write
# deny resolved. Exposed for request builders and tests.
READONLY_FIELDS = _deny_set("*", "write")


def can(role, entity, op):
    # Type-level: may role perform op on entity? A per-entity matrix entry
    # overrides the "*" default for that entity only.
    r = _ROLES.get(role)
    if not r or "matrix" not in r:
        return False
    matrix = r["matrix"]
    ops = matrix[entity] if entity in matrix else matrix.get("*")
    return isinstance(ops, list) and op in ops


def ownership_field(role, op):
    # Ownership: the owner field name if role is restricted to its own records for
    # op (e.g. author update/delete -> "createdBy"), else None.
    own = (_ROLES.get(role) or {}).get("ownership")
    if not own or op not in own["operations"]:
        return None
    return own["field"]


def is_governed(entity):
    return entity in _WORKFLOW


def status_property(entity):
    return _WORKFLOW[entity]["statusProperty"] if is_governed(entity) else None


def initial_status(entity):
    return _WORKFLOW[entity]["initial"] if is_governed(entity) else None


def transition_allowed(entity, frm, to, role):
    # May role move entity from frm to to? Non-governed entities and no-op
    # transitions (frm == to) are always allowed; everything else must be modelled.
    if not is_governed(entity):
        return True
    if frm == to:
        return True
    return any(
        t["from"] == frm and t["to"] == to and role in t["roles"]
        for t in _WORKFLOW[entity]["transitions"]
    )


def readonly_violations(role, body):
    # Field-level write: the names in body a role is not allowed to set (system and
    # internal fields). Any hit is a 400, not a silent drop.
    if not isinstance(body, dict):
        return []
    deny = _deny_set(role, "write")
    return [k for k in body.keys() if k in deny]


def strip_fields(role, value):
    # Field-level read: strip denied (internal) fields from a value before it
    # leaves the server, recursing into lists and embedded objects so embeds are
    # covered.
    deny = _deny_set(role, "read")

    def walk(v):
        if isinstance(v, list):
            return [walk(e) for e in v]
        if isinstance(v, dict):
            return {k: walk(val) for k, val in v.items() if k not in deny}
        return v

    return walk(value)


def apply_create_defaults(entity, data, account_id):
    # On create the server stamps ownership (createdBy) and forces the workflow
    # entry state, overriding any client-supplied status.
    out = {**data, "createdBy": account_id}
    initial = initial_status(entity)
    if initial is not None:
        out[status_property(entity)] = initial
    return out


def _read_visibility(role):
    # Anonymous read visibility: "public" gates status-bearing entities to their
    # public states; "all" returns every record.
    r = _ROLES.get(role) or {}
    return (r.get("read") or {}).get("visibility", "all")


def _parse_iso(value):
    # Lenient ISO 8601 parse for the datePublished gate; a trailing Z is accepted.
    if not isinstance(value, str):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def is_visible(role, entity, item):
    if _read_visibility(role) != "public":
        return True
    if not is_governed(entity):
        return True
    wf = _WORKFLOW[entity]
    if item.get(wf["statusProperty"]) not in wf["public"]:
        return False
    if wf["hasPublishDate"]:
        at = _parse_iso(item.get("datePublished"))
        if at is None or at > time.time():
            return False
    return True
