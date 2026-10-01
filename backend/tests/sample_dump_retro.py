"""Volcado de muestra de la colección RETRO (ROMs), formato MEGAcmd.

Reproduce lo que trae el in-share de ROMs: sistemas en el nivel 1 (`ARC …`), en
unos juegos-ARCHIVO sueltos (MAME), en otros juegos-carpeta agrupados por
carpeta-letra (`B/`, `#/`) y en otros un juego-carpeta con su variante `B-ASE`.
"""

SAMPLE_DUMP_RETRO = """\
VOLCADO DE CONTENIDO DE CUENTA MEGA (MEGAcmd)
========================================================================
Cuenta            : retro@example.com
Fecha de volcado  : 2026-09-30T00:00:00
Herramienta       : MEGAcmd 2.6.0 (mega-ls -R -l)
Archivos          : 7
Carpetas          : 11
Tamano total      : 2800 bytes

========================================================================
SECTOR: CLOUD_DRIVE
========================================================================
Archivos  : 0
Carpetas  : 1
Tamano    : 0 bytes (0 B)

[ROOT] //
`-- [FOLDER] Otros/

========================================================================
SECTOR: INSHARE duenio@example.com:ORTIK 90
========================================================================
Archivos  : 7
Carpetas  : 10
Tamano    : 2800 bytes

[ROOT] //from/duenio@example.com:ORTIK 90/
|-- [FOLDER] ARC Mame2003/
|   |-- [FILE] 3wonders.zip  (100 bytes)
|   `-- [FILE] aof.zip  (200 bytes)
|-- [FOLDER] ARC N-64/
|   |-- [FOLDER] #/
|   |   `-- [FOLDER] 1080 Snowboarding/
|   |       `-- [FILE] 1080 Snowboarding (Japan, USA).zip  (500 bytes)
|   `-- [FOLDER] B/
|       |-- [FOLDER] Banjo Kazooie/
|       |   `-- [FILE] Banjo-Kazooie (USA).zip  (300 bytes)
|       `-- [FOLDER] Banjo Tooie/
|           `-- [FILE] Banjo-Tooie (USA).zip  (400 bytes)
`-- [FOLDER] ARC 5NK-NE0GE0/
    |-- [FILE] alpham2.zip  (600 bytes)
    `-- [FOLDER] Aero Fighters 2/
        `-- [FOLDER] B-ASE/
            `-- [FILE] aero.part1.rar  (700 bytes)
"""
