# Upstream waits

1. The delivering upstream issue carries `export:<capability>`. With user
   approval, the waiting session files a missing issue or labels/comments an
   existing one:
   `board bd -C <upstream path> create … --assignee user --label export:<capability>`;
   description names the waiting issue.
2. Create the local wait:
   `board bd gate create --type=human --blocks <issue> --reason "waits for <project>:<capability>"`.
   Make further waiting issues depend on the same gate.
3. Upstream runs `board bd ship <capability>` at issue closure. The waiting
   session resolves the gate once
   `board bd -C <upstream path> list --label provides:<capability> --status closed`
   shows the capability.
