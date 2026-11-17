#!/usr/bin/env bash
# Fetch all catalog fonts (open source: OFL / Apache 2.0) from github.com/google/fonts
# into fonts/ and their license texts into fonts/licenses/. Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE="https://raw.githubusercontent.com/google/fonts/main"
mkdir -p fonts/licenses

# <license-dir> <family-dir> <remote file> <local file> <id>
FONTS='ofl tinos Tinos-Regular.ttf Tinos-Regular.ttf tinos
ofl arimo Arimo[wght].ttf Arimo-Variable.ttf arimo
ofl stylescript StyleScript-Regular.ttf StyleScript-Regular.ttf style-script
ofl mansalva Mansalva-Regular.ttf Mansalva-Regular.ttf mansalva
ofl alexbrush AlexBrush-Regular.ttf AlexBrush-Regular.ttf alex-brush
ofl marcellus Marcellus-Regular.ttf Marcellus-Regular.ttf marcellus
ofl montserrat Montserrat[wght].ttf Montserrat-Variable.ttf montserrat
ofl cormorantgaramond CormorantGaramond[wght].ttf CormorantGaramond-Variable.ttf cormorant-garamond
ofl bebasneue BebasNeue-Regular.ttf BebasNeue-Regular.ttf bebas-neue
ofl playfairdisplay PlayfairDisplay[wght].ttf PlayfairDisplay-Variable.ttf playfair-display
ofl inter Inter[opsz,wght].ttf Inter-Variable.ttf inter
ofl jost Jost[wght].ttf Jost-Variable.ttf jost
ofl ebgaramond EBGaramond[wght].ttf EBGaramond-Variable.ttf eb-garamond
ofl cinzel Cinzel[wght].ttf Cinzel-Variable.ttf cinzel
ofl bodonimoda BodoniModa[opsz,wght].ttf BodoniModa-Variable.ttf bodoni-moda
ofl abrilfatface AbrilFatface-Regular.ttf AbrilFatface-Regular.ttf abril-fatface
ofl righteous Righteous-Regular.ttf Righteous-Regular.ttf righteous
ofl cabin Cabin[wdth,wght].ttf Cabin-Variable.ttf cabin
ofl nunitosans NunitoSans[YTLC,opsz,wdth,wght].ttf NunitoSans-Variable.ttf nunito-sans
apache syncopate Syncopate-Regular.ttf Syncopate-Regular.ttf syncopate
ofl cormorant Cormorant[wght].ttf Cormorant-Variable.ttf cormorant
ofl fraunces Fraunces[SOFT,WONK,opsz,wght].ttf Fraunces-Variable.ttf fraunces
ofl dancingscript DancingScript[wght].ttf DancingScript-Variable.ttf dancing-script
ofl thenautigal TheNautigal-Regular.ttf TheNautigal-Regular.ttf the-nautigal
ofl parisienne Parisienne-Regular.ttf Parisienne-Regular.ttf parisienne
ofl caramel Caramel-Regular.ttf Caramel-Regular.ttf caramel
ofl caveat Caveat[wght].ttf Caveat-Variable.ttf caveat
ofl pacifico Pacifico-Regular.ttf Pacifico-Regular.ttf pacifico
ofl greatvibes GreatVibes-Regular.ttf GreatVibes-Regular.ttf great-vibes
ofl sacramento Sacramento-Regular.ttf Sacramento-Regular.ttf sacramento
ofl cedarvillecursive Cedarville-Cursive.ttf Cedarville-Cursive.ttf cedarville-cursive
ofl allison Allison-Regular.ttf Allison-Regular.ttf allison
ofl shadowsintolight ShadowsIntoLight.ttf ShadowsIntoLight.ttf shadows-into-light
ofl moondance MoonDance-Regular.ttf MoonDance-Regular.ttf moon-dance
ofl msmadi MsMadi-Regular.ttf MsMadi-Regular.ttf ms-madi
apache yellowtail Yellowtail-Regular.ttf Yellowtail-Regular.ttf yellowtail
'

urlenc() { printf '%s' "$1" | sed -e 's/\[/%5B/g' -e 's/\]/%5D/g' -e 's/,/%2C/g'; }

fail=0
while read -r lic dir remote local id; do
  [[ -z "$lic" ]] && continue
  if [[ ! -s "fonts/$local" ]]; then
    echo "fetching $local"
    curl -fsSL "$BASE/$lic/$dir/$(urlenc "$remote")" -o "fonts/$local" || { echo "FAILED $local" >&2; rm -f "fonts/$local"; fail=1; }
  fi
  lic_file=OFL.txt; [[ "$lic" == "apache" ]] && lic_file=LICENSE.txt
  out="fonts/licenses/$id-${lic_file%.txt}.txt"
  if [[ ! -s "$out" ]]; then
    if ! curl -fsSL "$BASE/$lic/$dir/$lic_file" -o "$out" 2>/dev/null; then
      # Some families ship no license file in google/fonts (e.g. Tinos, METADATA says OFL):
      # use the OFL 1.1 text of the sibling family Arimo (same designer) with a note.
      { echo "NOTE: google/fonts has no license file for '$id' (METADATA: license OFL). Standard OFL 1.1 text of sibling family Arimo follows; check the upstream source."; echo;
        curl -fsSL "$BASE/ofl/arimo/OFL.txt"; } > "$out" || { echo "no license text for $id" >&2; rm -f "$out"; }
    fi
  fi
done <<< "$FONTS"
[[ $fail -eq 0 ]] && echo "done: $(ls fonts/*.ttf | wc -l) font files" || { echo "some fonts failed" >&2; exit 1; }
