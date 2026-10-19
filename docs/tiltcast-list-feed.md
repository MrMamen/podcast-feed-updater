# Tiltcast-listefeeder

`build_list_feed.py` bygger RSS-feeder fra Podchaser-lista
[Episoder fra Tiltcast i Oslo](https://www.podchaser.com/lists/episoder-fra-tiltcast-i-oslo-11SK7Mk5jl).
Podchaser har bare en statisk RSS-eksport. Disse feedene oppdateres når lista endres, og
henter episoder fra mange podcaster.

- `tiltcast-all.xml`: alle episodene, én `podcast:season` per utgave
- `tiltcast-1.xml` … `tiltcast-N.xml`: én feed per utgave (seksjon i lista), i listas rekkefølge

```bash
uv run build_list_feed.py --list tiltcast    # lokalt, med Podchaser-nøkler i .env
```

På GitHub: Actions → **Build Tiltcast List Feed**. Oppsettet står i `podcasts/tiltcast/list.toml`.

## Ny utgave

Legg til en seksjonsoverskrift og episodene i lista på Podchaser. Legg coveret i
`podcasts/tiltcast/images/tiltcast-<nr>.jpg` eller `.png`, kvadratisk og 1400–3000 px.
Kjør så bygget. Uten cover bygges feeden likevel, bare uten kanalbilde.

## Verdt å vite

- **`list_id` er Podchasers numeriske id, ikke hashid-en i URL-en.** Hashid-en gir en annen liste.
- **Kostnad:** rundt 18 poeng per episode av 25 000 i måneden. Bygget sjekker prisen gratis
  først, og avbryter hvis saldoen ville falt under `min_remaining`.
- **Lyd-URL-er brukes som de er,** så OP3-prefikset til cd SPILL beholdes.
- **`itunes:episodeType` er alltid `full`,** og `itunes:explicit` beregnes ut fra episodene.
- **`itunes:type`:** den samlede feeden og nyeste utgave er `episodic`, så apper laster ned
  nye episoder. Avsluttede utgaver bruker `itunes_type` (`serial`).
- **`pubDate`:** nyeste utgave beholder ekte dato, så nye episoder varsles. Eldre utgaver
  får datoen fra overskriften (f.eks. «lørdag 30. mai 2026»), med én time mellom episodene,
  så de vises i rekkefølgen fra lista. Når en ny utgave starter, går den forrige automatisk
  over til dette. GUID-ene er de samme hele veien.
