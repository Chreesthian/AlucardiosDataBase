"""Volcado de muestra en el formato exacto de MEGAcmd (mega-ls -R -l)."""

SAMPLE_DUMP = """\
VOLCADO DE CONTENIDO DE CUENTA MEGA (MEGAcmd)
========================================================================
Cuenta            : test@example.com
Fecha de volcado  : 2026-09-07T00:00:00
Herramienta       : MEGAcmd 2.6.0 (mega-ls -R -l)
Archivos          : 6
Carpetas          : 10
Tamano total      : 1012586004 bytes

========================================================================
SECTOR: CLOUD_DRIVE
========================================================================
Archivos  : 0
Carpetas  : 1
Tamano    : 0 bytes (0 B)

[ROOT] //
`-- [FOLDER] S4 Object storage/

========================================================================
SECTOR: INBOX
========================================================================
Archivos  : 0
Carpetas  : 1
Tamano    : 0 bytes (0 B)

[ROOT] //in/
`-- [FOLDER] Backups/

========================================================================
SECTOR: RUBBISH_BIN
========================================================================
Archivos  : 0
Carpetas  : 0
Tamano    : 0 bytes (0 B)

[ROOT] //bin/

========================================================================
SECTOR: INSHARE test@example.com:BCKP1
========================================================================
Archivos  : 6
Carpetas  : 10
Tamano    : 1012586004 bytes

[ROOT] //from/test@example.com:BCKP1/
|-- [FOLDER] -- A/
|   |-- [FOLDER] A Game One/
|   |   |-- [FOLDER] B-ASE/
|   |   |   |-- [FILE] game1.part1.rar  (104857600 bytes)
|   |   |   `-- [FILE] game1.part2.rar  (104857600 bytes)
|   |   |-- [FOLDER] U-PD 1.0.1/
|   |   |   `-- [FILE] game1.101.part1.rar  (5242880 bytes)
|   |   `-- [FOLDER] D-LC/
|   |       `-- [FILE] game1.dlc1.part1.rar  (1024 bytes)
|   `-- [FOLDER] A Second Game/
|       `-- [FOLDER] B-ASE/
|           `-- [FILE] game2 8453.part1.rar  (734003200 bytes)
|-- [FOLDER] -- Z/
|   `-- [FOLDER] Zelda Echoes of Wisdom/
|       `-- [FOLDER] B-ASE/
|           `-- [FILE] zelda-eow [v0][US](nsw2u.com).nsp  (55350596 bytes)
"""
