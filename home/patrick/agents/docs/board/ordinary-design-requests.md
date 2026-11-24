# Separate design change requests

A design lands with its implementation in the same change request (CR) by default ([model.md](model.md#change-request-fields)). This is the contract for the exception, a separate design CR that names its reason (`nixes-lwf8q`). It carries the design through ordinary review and Accept; no checkpoint stage exists.

## Contract

- Plan the design CR with `design` items (the `kind:design` label) that commit the design to the existing topic owner under `docs/`, carrying its scope, constraints, authority and validation criteria in the committed text. Use the project's normal `look`; use `look before` when the design opens a one-way door on the next run's path.
- Closing the items records the authoring pass; landing the CR delivers the approved design. Review, Return, refresh, `review open`, the user's edits and Accept operate on the committed range like any CR's. The accepted text lives on the target, where Release applies later rulings through its owner-write path.
- Cut the implementation CR after the design CR lands and cite the document section in its brief. A CR that needs the accepted design waits on the design CR (`agents board wait`): it starts after the landing, or stacks on the design CR once that is `passed` ([Waiting and stacks](../../skills/shared/change-requests.md#change-requests)). At implementation acceptance, update the design owner with verified behavior and the remaining validation scope.
- An open question holds only the items it changes. A ruling that changes an in-review design returns it through the planner's `return --ruling`. Review and Return carry the same authority as for other CRs.
- A design landed through `look after` needs no confirmation of its own: the user judges its choice records afterwards ([model.md](model.md#after-the-fact-look-after)).

Existing records of the retired design checkpoint convert once, through board-migrate; the runtime keeps no reader for them.
