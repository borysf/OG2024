#!/usr/bin/env python3
"""Assemble a single JSON response from downloaded tmp/ files.

Writes output to example.json by default.

Usage:
  ./scripts/assemble_api_response.py --comp OG2024 --event FBLMTEAM11 --lang ENG --tmp tmp --out example.json
"""

import argparse
import json
import os
import re


def canonicalize_event(ev, length=22, pad_char='-'):
    if ev is None:
        return ev
    if len(ev) >= length:
        return ev
    return ev.ljust(length, pad_char)


def load_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def find_res_file(tmp_dir, comp, disc, unit_code, lang):
    fname = f"RES_ByRSC_H2H~comp={comp}~disc={disc}~rscResult={unit_code}~lang={lang}.json"
    path = os.path.join(tmp_dir, fname)
    return path if os.path.exists(path) else None


def _select_unit(units, prefer_unit=None):
    # prefer explicit unit if provided
    if prefer_unit:
        for u in units:
            if u.get('code') and prefer_unit in u.get('code'):
                return u
        # exact match fallback
        for u in units:
            if u.get('code') == prefer_unit:
                return u
    # try to find a final/gold match
    for u in units:
        c = u.get('code', '')
        if 'FNL-000100' in c or 'FNL' in c:
            return u
    # else return first unit with schedule
    for u in units:
        if u.get('schedule'):
            return u
    return units[0] if units else None


def _parse_minute(pb_when):
    # pb_when examples: "25'", "105'", "105' +3", "120'"
    if not pb_when:
        return None
    m = re.search(r"(\d{1,3})", str(pb_when))
    return int(m.group(1)) if m else None


def _collect_scorers(res_json, athlete_map, team_map):
    scorers = []
    for sub in res_json.get('playByPlay', []):
        for act in sub.get('actions', []):
            result = act.get('pbpa_Result') or act.get('pbpa_Result')
            action = act.get('pbpa_Action')
            # treat GOAL actions (or PEN with GOAL) as scorer entries
            if (result and 'GOAL' in str(result).upper()) or action in ('PEN',):
                comps = act.get('competitors', [])
                if not comps:
                    continue
                comp = comps[0]
                team_code = comp.get('pbpc_code') or comp.get('pbpc_code')
                team_name = team_map.get(team_code)
                athletes = comp.get('athletes', [])
                scorer = None
                assist = None
                for ath in athletes:
                    role = ath.get('pbpat_role', '')
                    code = ath.get('pbpat_code')
                    if role and role.upper().startswith('SCR') or role == 'SCR':
                        scorer = {'player': athlete_map.get(code), 'minute': _parse_minute(act.get('pbpa_When'))}
                    elif role and role.upper().startswith('ASS') or role == 'ASSIST' or role == 'ASS':
                        assist = athlete_map.get(code)
                # fallback: if no role info, take first athlete code as scorer
                if not scorer and athletes:
                    code = athletes[0].get('pbpat_code')
                    scorer = {'player': athlete_map.get(code), 'minute': _parse_minute(act.get('pbpa_When'))}
                if scorer:
                    entry = {'team': team_name or team_code, 'player': scorer.get('player'), 'minute': scorer.get('minute')}
                    if assist:
                        entry['assist'] = assist
                    # rudimentary type detection
                    t = 'open_play'
                    if 'PEN' in (act.get('pbpa_Result') or '') or act.get('pbpa_period') == 'PET' or act.get('pbpa_period') == 'PEN':
                        t = 'penalty'
                    entry['type'] = t
                    scorers.append(entry)
    return scorers


def _build_lineup(team_item):
    lineup = {
        'team': team_item.get('participant', {}).get('name') if team_item.get('participant') else team_item.get('participant', {}).get('name') if team_item.get('participant') else None,
        'formation': None,
        'coach': None,
        'startingXI': [],
        'bench': [],
    }
    # formation & coaches
    for eue in team_item.get('eventUnitEntries', []):
        if eue.get('eue_code') == 'FORMATION':
            lineup['formation'] = eue.get('eue_value')
    coaches = team_item.get('teamCoaches') or []
    if coaches:
        lineup['coach'] = coaches[0].get('coach', {}).get('name')

    starters = []
    bench = []
    for ath in team_item.get('teamAthletes', []):
        athlete = ath.get('athlete') or {}
        name = athlete.get('name') or f"{ath.get('participantCode')}"
        number = int(ath.get('bib')) if ath.get('bib') and str(ath.get('bib')).isdigit() else ath.get('bib')
        position = None
        for eue in ath.get('eventUnitEntries', []):
            if eue.get('eue_code') == 'POSITION':
                position = eue.get('eue_value')
        is_starter = any(e.get('eue_code') == 'STARTER' and (e.get('eue_value') == 'Y' or e.get('eue_value') == '1') for e in ath.get('eventUnitEntries', []))
        entry = {'name': name, 'number': number, 'position': position}
        if is_starter:
            starters.append(entry)
        else:
            bench.append(entry)
    lineup['startingXI'] = starters
    lineup['bench'] = bench
    return lineup


def assemble(comp, event, lang, tmp_dir, template_path='endpoint-template.json', unit_pref=None, all_units=False):
    event_code = canonicalize_event(event)
    result = {}
    used_files = set()

    # main event games file
    main_fname = f"GLO_EventGames~comp={comp}~event={event_code}~lang={lang}.json"
    main_path = os.path.join(tmp_dir, main_fname)
    main_json = load_json(main_path)
    if main_json is None:
        raise SystemExit(f"Missing main file: {main_path}")
    used_files.add(main_fname)

    # assemble base event info
    event_obj = main_json.get('event', {})

    # collect units
    units = []
    for phase in event_obj.get('phases', []):
        for unit in phase.get('units', []) if isinstance(phase.get('units'), list) else []:
            units.append(unit)

    template = load_json(template_path)
    if not template:
        raise SystemExit(f"Missing template file: {template_path}")
    placeholder_key = list(template.keys())[0]
    template_body = template[placeholder_key]

    # decide target units
    if all_units:
        target_units = units
    else:
        sel = _select_unit(units, unit_pref)
        if sel is None:
            raise SystemExit("No units found in main event file")
        target_units = [sel]

    final = {}

    for selected_unit in target_units:
        unit_code = selected_unit.get('code')

        # load RES file for unit
        res_path = find_res_file(tmp_dir, comp, 'FBL', unit_code, lang)
        res_json = load_json(res_path) if res_path else None
        if res_path:
            used_files.add(os.path.basename(res_path))

        # shallow copy to mutate per-unit
        out_body = json.loads(json.dumps(template_body))

        # Fill competition
        out_body.setdefault('competition', {})
        out_body['competition']['name'] = event_obj.get('longDescription') or event_obj.get('description') or out_body['competition'].get('name')
        out_body['competition']['season'] = comp
        out_body['competition']['round'] = selected_unit.get('shortDescription') or selected_unit.get('description') or out_body['competition'].get('round')

        # Fill venue / kickoff / status
        if res_json:
            # some RES files wrap the useful data under `results`
            res = res_json.get('results', res_json)
            schedule = res.get('schedule', {})
            venue = schedule.get('venue') or {}
            location = schedule.get('location') or {}
            out_body.setdefault('venue', {})
            out_body['venue']['name'] = venue.get('description') or out_body['venue'].get('name')
            # try to get city from location
            city = location.get('shortDescription') or (location.get('longDescription').split(',')[-1].strip() if location.get('longDescription') else None)
            out_body['venue']['city'] = city or out_body['venue'].get('city')

            out_body['kickoff'] = schedule.get('startDate') or out_body.get('kickoff')
            # status from extendedInfos PERIOD
            status = None
            for ei in res.get('extendedInfos', []):
                if ei.get('ei_code') == 'PERIOD' or ei.get('ei_code') == 'PERIOD':
                    status = ei.get('ei_value')
                    break
            out_body['status'] = status or out_body.get('status')

            # teams mapping
            home_name = None
            away_name = None
            start_info = schedule.get('start') or selected_unit.get('schedule', {}).get('start')
            if start_info:
                for s in start_info:
                    so = s.get('startOrder')
                    pname = s.get('participant', {}).get('name')
                    if so == 1:
                        home_name = pname
                    elif so == 2:
                        away_name = pname
            # fallback to items ordering
            items = res.get('items', [])
            if not (home_name and away_name) and items and len(items) >= 2:
                home_name = items[0].get('participant', {}).get('name')
                away_name = items[1].get('participant', {}).get('name')

            out_body.setdefault('teams', {})
            out_body['teams']['home'] = home_name or out_body['teams'].get('home')
            out_body['teams']['away'] = away_name or out_body['teams'].get('away')

            # score
            out_body.setdefault('score', {})
            tot = next((p for p in res.get('periods', []) if p.get('p_code') == 'TOT'), None)
            if tot:
                out_body['score']['home'] = int(tot.get('home', {}).get('score') or 0)
                out_body['score']['away'] = int(tot.get('away', {}).get('score') or 0)
            h1 = next((p for p in res.get('periods', []) if p.get('p_code') == 'H1'), None)
            if h1:
                out_body['score'].setdefault('halfTime', {})
                out_body['score']['halfTime']['home'] = int(h1.get('home', {}).get('score') or 0)
                out_body['score']['halfTime']['away'] = int(h1.get('away', {}).get('score') or 0)

            # build helper maps
            athlete_map = {}
            team_map = {}
            for itm in res.get('items', []):
                team_map[itm.get('teamCode')] = itm.get('participant', {}).get('name')
                for ath in itm.get('teamAthletes', []):
                    code = ath.get('participantCode')
                    name = ath.get('athlete', {}).get('name') or ath.get('athlete', {}).get('shortName')
                    athlete_map[code] = name

            # scorers
            out_body['scorers'] = _collect_scorers(res, athlete_map, team_map)

            # lineups (per-team)
            out_body.setdefault('lineups', {})
            for idx, itm in enumerate(res.get('items', [])):
                team_name = itm.get('participant', {}).get('name')
                lineup = _build_lineup(itm)
                # determine home/away by name match
                if team_name == out_body['teams'].get('home'):
                    out_body['lineups']['home'] = lineup
                elif team_name == out_body['teams'].get('away'):
                    out_body['lineups']['away'] = lineup
            # fallback if not set, assign based on ordering
            if 'home' not in out_body['lineups'] and res.get('items'):
                out_body['lineups']['home'] = _build_lineup(res.get('items')[0])
            if 'away' not in out_body['lineups'] and len(res.get('items')) > 1:
                out_body['lineups']['away'] = _build_lineup(res.get('items')[1])

        else:
            # no res file: best-effort fill from main
            out_body['kickoff'] = selected_unit.get('schedule', {}).get('startDate') or out_body.get('kickoff')
            out_body['status'] = (selected_unit.get('schedule', {}).get('status', {}).get('code')) or out_body.get('status')
            # teams
            start_arr = selected_unit.get('schedule', {}).get('start') or []
            if start_arr and len(start_arr) >= 2:
                out_body.setdefault('teams', {})
                out_body['teams']['home'] = start_arr[0].get('participant', {}).get('name')
                out_body['teams']['away'] = start_arr[1].get('participant', {}).get('name')

        # set endpoint key: parametrized dummy URL
        url_key = f"/api/scores?comp={comp}&event={event}&unit={unit_code}&lang={lang}"
        final[url_key] = out_body

    final['generated_from'] = sorted(list(used_files))
    return final


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--comp', default='OG2024')
    p.add_argument('--event', default='FBLMTEAM11')
    p.add_argument('--lang', default='ENG')
    p.add_argument('--tmp', default='tmp')
    p.add_argument('--template', default='endpoint-template.json', help='Path to endpoint template JSON')
    p.add_argument('--unit', default=None, help='Optional unit code (or substring) to select a specific match unit')
    p.add_argument('--all-units', action='store_true', help='Generate endpoints for all units (default selects one unit)')
    p.add_argument('--out', default='example.json')
    args = p.parse_args()

    assembled = assemble(args.comp, args.event, args.lang, args.tmp, template_path=args.template, unit_pref=args.unit, all_units=args.all_units)

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(assembled, f, indent=2, ensure_ascii=False)

    print(f"Wrote assembled response to {args.out}")


if __name__ == '__main__':
    main()
