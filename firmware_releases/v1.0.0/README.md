# v1.0.0 — versão funcional (baseline)

Backup do firmware testado e confirmado funcionando (gravado via aba
Firmware do OrbePC, esptool, sem Arduino IDE no cliente).

- `OrbePC_firmware_v1.0.0.bin` — o `.ino.merged.bin` exportado, pronto pra
  selecionar na aba Firmware do app (offset `0x0`).
- `painel_pc_esp32c3_v1.0.0.ino` — cópia exata do código-fonte que gerou
  esse binário, pra referência/rollback caso as próximas melhorias
  quebrem algo.

Não mexer nestes dois arquivos. Trabalhe as melhorias em
`painel_pc_esp32c3/painel_pc_esp32c3.ino` (o original, fora desta pasta) —
quando a próxima versão estiver testada e funcionando, repete o mesmo
processo numa pasta `firmware_releases/vX.Y.Z/` nova.
