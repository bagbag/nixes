# Upstream waits

1. The delivering upstream record carries `export:<capability>`. With user
   approval, the waiting session files a missing task or labels/comments an
   existing one:
   `cd <upstream path> && agents board create <title> -t task --no-commit --label export:<capability>`
   (`agents board create` acts on the board of the folder it runs in);
   description names the waiting item. Another person's step there is a human
   gate on their board.
   Output: the upstream record id.
2. Create the local wait:
   `agents board gate create --blocks <item> --reason "waits for <project>:<capability>"`.
   Make further waiting items wait on the same gate
   (`agents board wait <item> --on <gate>`).
   Output: the gate id.
3. Upstream runs `agents board bd --raw --yes ship <capability>` at closure. The waiting
   session resolves the gate (`agents board gate resolve <gate>`; a deciding session or the user, so a planning session asks one) once
   `agents board bd -C <upstream path> list --label provides:<capability> --status closed`
   shows the capability.
   Output: gate resolved, or still waiting.
