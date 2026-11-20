# Upstream waits

1. The delivering upstream issue carries `export:<capability>`. With user
   approval, the waiting session files a missing issue or labels/comments an
   existing one:
   `cd <upstream path> && board create <title> … --assignee user --label export:<capability>`
   (`agents board create` acts on the board of the folder it runs in);
   description names the waiting issue.
   Output: the upstream issue id.
2. Create the local wait:
   `agents board gate create --blocks <issue> --reason "waits for <project>:<capability>"`.
   Make further waiting issues depend on the same gate (`agents board block <issue> --on <gate>`).
   Output: the gate id.
3. Upstream runs `agents board bd --raw --yes ship <capability>` at issue closure. The waiting
   session resolves the gate (`agents board gate resolve <gate>`) once
   `agents board bd -C <upstream path> list --label provides:<capability> --status closed`
   shows the capability.
   Output: gate resolved, or still waiting.
