#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
# When copied into the repo root, ROOT is the repository root. When executed
# from an extracted subfolder, allow --repo style by simply moving the file or
# running it after copying the overlay. This is intentionally dependency-free.


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Patch marker {label!r} expected once, found {count}")
    return text.replace(old, new, 1)


def patch_dashboard(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .lineups import analyze_5v5_lineups\n",
        "from .lineups import analyze_5v5_lineups\nfrom .del_insight import load_game_insight, load_latest_snapshot, team_season_summary\n",
        "dashboard import",
    )

    helper = '''\n\ndef _insight_preview_rows(ebb: dict[str, Any] | None, opp: dict[str, Any] | None) -> list[dict[str, Any]]:\n    if not ebb and not opp:\n        return []\n\n    def pair(row: dict[str, Any] | None, a: str, b: str) -> str | None:\n        if not row:\n            return None\n        av, bv = row.get(a), row.get(b)\n        if av is None and bv is None:\n            return None\n        return f"{int(av or 0)} / {int(bv or 0)}"\n\n    specs = [\n        ("Pässe", pair(ebb, "passes_completed", "passes_attempted"), pair(opp, "passes_completed", "passes_attempted"), "text"),\n        ("Passquote", (ebb or {}).get("pass_pct"), (opp or {}).get("pass_pct"), "percent"),\n        ("Puck Contests", pair(ebb, "pcw_won", "pcw_total"), pair(opp, "pcw_won", "pcw_total"), "text"),\n        ("PCW%", (ebb or {}).get("pcw_pct"), (opp or {}).get("pcw_pct"), "percent"),\n        ("xG Summe", (ebb or {}).get("xg_sum"), (opp or {}).get("xg_sum"), "decimal2"),\n        ("xG / Spiel", (ebb or {}).get("xg_per_game"), (opp or {}).get("xg_per_game"), "decimal2"),\n    ]\n    return [{"label": label, "ebb": a, "opponent": b, "kind": kind} for label, a, b, kind in specs]\n'''
    text = replace_once(text, "\ndef enrich_upcoming_games(", helper + "\n\ndef enrich_upcoming_games(", "insight preview helper")

    text = replace_once(
        text,
        'def enrich_upcoming_games(con: Any, games: list[dict[str, Any]], *, raw_dir: Path = Path("data/raw")) -> list[dict[str, Any]]:',
        'def enrich_upcoming_games(con: Any, games: list[dict[str, Any]], *, raw_dir: Path = Path("data/raw"), insight_dir: Path = Path("data/del_insight")) -> list[dict[str, Any]]:',
        "enrich signature",
    )
    text = replace_once(
        text,
        "    ebb_stats = _season_key_stats(con, FOCUS_TEAM_ID)\n    ebb_recent = _recent_games(con, FOCUS_TEAM_ID, limit=5)\n",
        "    ebb_stats = _season_key_stats(con, FOCUS_TEAM_ID)\n    ebb_recent = _recent_games(con, FOCUS_TEAM_ID, limit=5)\n    insight_snapshot = load_latest_snapshot(insight_dir)\n    ebb_insight = team_season_summary(insight_snapshot, FOCUS_TEAM_ID, games_played=int(ebb_stats.get(\"games_played\") or 0))\n",
        "enrich bootstrap",
    )
    text = replace_once(
        text,
        "        opponent_stats = _season_key_stats(con, opponent_team_id)\n",
        "        opponent_stats = _season_key_stats(con, opponent_team_id)\n        opponent_insight = team_season_summary(insight_snapshot, opponent_team_id, games_played=int(opponent_stats.get(\"games_played\") or 0))\n",
        "opponent insight",
    )
    text = replace_once(
        text,
        '                "key_stats": _key_stat_rows(ebb_stats, opponent_stats),\n',
        '                "key_stats": _key_stat_rows(ebb_stats, opponent_stats),\n                "del_insight": {\n                    "available": bool(ebb_insight or opponent_insight),\n                    "snapshot_at": (insight_snapshot or {}).get("generated_at_utc"),\n                    "rows": _insight_preview_rows(ebb_insight, opponent_insight),\n                },\n',
        "upcoming payload",
    )

    text = replace_once(
        text,
        "def build_game_payload(con: Any, match_id: int) -> dict[str, Any]:",
        'def build_game_payload(con: Any, match_id: int, *, insight_dir: Path = Path("data/del_insight")) -> dict[str, Any]:',
        "game payload signature",
    )
    before_facts = '''    facts = _build_facts(ebb, players, lineups, advanced)\n'''
    insight_block = '''    raw_game_insight = load_game_insight(insight_dir, match_id)\n    game_insight = None\n    if raw_game_insight:\n        insight_teams = raw_game_insight.get("teams") or {}\n        ebb_insight = insight_teams.get(str(FOCUS_TEAM_ID))\n        opponent_insight = insight_teams.get(str(opponent_team_id))\n        game_insight = {\n            "available": bool(ebb_insight or opponent_insight),\n            "method": raw_game_insight.get("method"),\n            "ebb": ebb_insight,\n            "opponent": opponent_insight,\n            "unavailable": raw_game_insight.get("unavailable") or {},\n        }\n\n    facts = _build_facts(ebb, players, lineups, advanced)\n    if game_insight and game_insight.get("ebb") and game_insight.get("opponent"):\n        ebb_i = game_insight["ebb"].get("summary") or {}\n        opp_i = game_insight["opponent"].get("summary") or {}\n        if ebb_i.get("xg_sum") is not None and opp_i.get("xg_sum") is not None:\n            facts.append(\n                f"DEL Insight: xG {float(ebb_i['xg_sum']):.2f}:{float(opp_i['xg_sum']):.2f}; "\n                f"Passquote {float(ebb_i.get('pass_pct') or 0):.1f}%:{float(opp_i.get('pass_pct') or 0):.1f}%; "\n                f"Puck Contests {float(ebb_i.get('pcw_pct') or 0):.1f}%:{float(opp_i.get('pcw_pct') or 0):.1f}%."\n            )\n'''
    text = replace_once(text, before_facts, insight_block, "game insight block")
    text = replace_once(
        text,
        '        "advanced": advanced, "scoring_summary": scoring_summary,\n',
        '        "advanced": advanced, "scoring_summary": scoring_summary, "del_insight": game_insight,\n',
        "game payload return",
    )

    text = replace_once(
        text,
        '    raw_dir: Path = Path("data/raw"),\n    output_dir: Path = Path("site/data"),',
        '    raw_dir: Path = Path("data/raw"),\n    insight_dir: Path = Path("data/del_insight"),\n    output_dir: Path = Path("site/data"),',
        "generate signature",
    )
    text = replace_once(
        text,
        '            payload = build_game_payload(con, int(match["match_id"]))\n',
        '            payload = build_game_payload(con, int(match["match_id"]), insight_dir=insight_dir)\n',
        "build payload call",
    )
    text = replace_once(
        text,
        '            "upcoming_games": enrich_upcoming_games(con, upcoming_basic, raw_dir=raw_dir),\n',
        '            "upcoming_games": enrich_upcoming_games(con, upcoming_basic, raw_dir=raw_dir, insight_dir=insight_dir),\n',
        "upcoming call",
    )
    path.write_text(text, encoding="utf-8")


def patch_generate(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))\n',
        '    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))\n    parser.add_argument("--insight-dir", type=Path, default=Path("data/del_insight"))\n',
        "generate arg",
    )
    text = replace_once(
        text,
        "        raw_dir=args.raw_dir,\n        output_dir=args.output_dir,\n",
        "        raw_dir=args.raw_dir,\n        insight_dir=args.insight_dir,\n        output_dir=args.output_dir,\n",
        "generate pass arg",
    )
    path.write_text(text, encoding="utf-8")


def patch_workflow(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "python scripts/validate_season.py --allow-incomplete" not in text:
        text = text.replace("run: python scripts/validate_season.py", "run: python scripts/validate_season.py --allow-incomplete")
    if "Update DEL Insight stats" not in text:
        marker = "      - name: Build EBB dashboard data\n"
        block = '''      - name: Update DEL Insight stats\n        run: |\n          # Public PENNY DEL / Wisehockey aggregates are optional. A fetch or\n          # parser issue must never stop the main DEL pipeline.\n          python scripts/update_del_insight.py \\\n            --season 2026-27 \\\n            --phase hauptrunde \\\n            --output-dir data/del_insight \\\n            --discovery data/discovery/season_2026_27_type_1.json\n\n'''
        text = replace_once(text, marker, block + marker, "workflow insight step")
    if "--insight-dir data/del_insight" not in text:
        text = replace_once(
            text,
            "            --discovery data/discovery/season_2026_27_type_1.json \\\n            --output-dir site/data \\\n",
            "            --discovery data/discovery/season_2026_27_type_1.json \\\n            --insight-dir data/del_insight \\\n            --output-dir site/data \\\n",
            "workflow dashboard insight arg",
        )
    text = text.replace("git add data/raw data/discovery data/reports site/data", "git add data/raw data/discovery data/reports data/del_insight site/data")
    if "            data/del_insight\n" not in text:
        text = replace_once(
            text,
            "            data/reports/season_update_summary.json\n            site/\n",
            "            data/reports/season_update_summary.json\n            data/del_insight\n            site/\n",
            "workflow artifact insight",
        )
    path.write_text(text, encoding="utf-8")


def patch_site(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if ".insight-table" not in text:
        text = replace_once(text, ".zone-start-table {\n  min-width: 580px;\n}\n", ".zone-start-table {\n  min-width: 580px;\n}\n\n.insight-table {\n  min-width: 820px;\n}\n", "insight css")

    markup = '''\n  <section class="panel section" id="delInsightPanel" style="display:none"><h2>DEL Insight · Spieltag</h2><p class="muted" style="margin-bottom:10px">Offizielle PENNY-DEL/Wisehockey-Werte. Spielwerte werden als Differenz zweier kumulierter DEL-Snapshots vor/nach dem Spiel abgeleitet.</p><div id="delInsightStatus" class="data-check"></div><div class="scroll"><table class="data-table insight-table"><thead><tr><th>Team</th><th>Pässe</th><th>Pass%</th><th>Puck Contests</th><th>PCW%</th><th>xG</th><th>Tore</th><th>G-xG</th></tr></thead><tbody id="delInsightTeams"></tbody></table></div><h3 style="margin-top:16px">Spieler</h3><div class="scroll"><table class="data-table insight-table"><thead><tr><th>Team</th><th>Spieler</th><th>Pässe</th><th>Pass%</th><th>Puck Contests</th><th>PCW%</th><th>xG</th><th>BKS</th></tr></thead><tbody id="delInsightPlayers"></tbody></table></div></section>\n'''
    if "id=\"delInsightPanel\"" not in text:
        text = replace_once(text, "\n  <section class=\"panel section\">\n    <h2>EBB Player Usage</h2>", markup + "\n  <section class=\"panel section\">\n    <h2>EBB Player Usage</h2>", "insight markup")

    text = replace_once(
        text,
        "if(kind==='decimal')return Number(v).toFixed(1);return String(v)};",
        "if(kind==='decimal')return Number(v).toFixed(1);if(kind==='decimal2')return Number(v).toFixed(2);return String(v)};",
        "decimal2 formatter",
    )

    helpers = '''\n  const pairText=(a,b)=>a==null&&b==null?'–':`${Number(a||0).toLocaleString('de-DE')} / ${Number(b||0).toLocaleString('de-DE')}`;\n  const insightPreviewHtml=(g,opp)=>{const ins=g.del_insight||{};if(!ins.available||!(ins.rows||[]).length)return'';return `<div><h3>DEL Insight · Saison</h3><div class="scroll"><table class="preview-table"><thead><tr><th>Stat</th><th>EBB</th><th>${esc(opp)}</th></tr></thead><tbody>${ins.rows.map(x=>`<tr><td>${esc(x.label)}</td><td class="ebb">${esc(fmtVal(x.ebb,x.kind))}</td><td class="opp">${esc(fmtVal(x.opponent,x.kind))}</td></tr>`).join('')}</tbody></table></div><div class="note">Quelle: PENNY DEL / Wisehockey · Snapshot ${ins.snapshot_at?esc(new Date(ins.snapshot_at).toLocaleString('de-DE')):'–'}</div></div>`};\n'''
    if "insightPreviewHtml" not in text:
        text = replace_once(text, "  const recentHtml=rows=>rows.length?rows.map(r=>`<div class=\"recent-row\"><strong>${esc(r.outcome)}</strong><span>${esc(r.opponent_shortcut||r.opponent_name)}</span><span>${esc(r.result)}</span></div>`).join(''):'<div class=\"muted\">Noch keine Spiele.</div>';\n", "  const recentHtml=rows=>rows.length?rows.map(r=>`<div class=\"recent-row\"><strong>${esc(r.outcome)}</strong><span>${esc(r.opponent_shortcut||r.opponent_name)}</span><span>${esc(r.result)}</span></div>`).join(''):'<div class=\"muted\">Noch keine Spiele.</div>';\n" + helpers, "insight js helpers")

    if "${insightPreviewHtml(g,opp)}" not in text:
        key_block = '''      <div><h3>Key Stats</h3><div class="scroll"><table class="preview-table"><thead><tr><th>Stat</th><th>EBB</th><th>${esc(opp)}</th></tr></thead><tbody>${(g.key_stats||[]).map(x=>`<tr><td>${esc(x.label)}</td><td class="ebb">${esc(fmtVal(x.ebb,x.kind))}</td><td class="opp">${esc(fmtVal(x.opponent,x.kind))}</td></tr>`).join('')}</tbody></table></div></div>\n'''
        text = replace_once(text, key_block, key_block + "      ${insightPreviewHtml(g,opp)}\n", "preview insight html")

    text = replace_once(
        text,
        "renderScoring();renderUsage();renderImpact();",
        "renderScoring();renderInsight();renderUsage();renderImpact();",
        "render insight call",
    )

    render_insight = '''\n  function renderInsight(){const ins=state.game?.del_insight,panel=$('#delInsightPanel');if(!ins||!ins.available){panel.style.display='none';return}panel.style.display='block';const ebb=ins.ebb,opp=ins.opponent,oppAbbr=state.game?.opponent?.abbr||'Gegner';const teamRow=(label,data,cls)=>{if(!data)return'';const s=data.summary||{};return `<tr><td class="${cls}">${esc(label)}</td><td>${pairText(s.passes_completed,s.passes_attempted)}</td><td>${pct(s.pass_pct)}</td><td>${pairText(s.pcw_won,s.pcw_total)}</td><td>${pct(s.pcw_pct)}</td><td><b>${s.xg_sum==null?'–':Number(s.xg_sum).toFixed(2)}</b></td><td>${s.goals??'–'}</td><td>${s.xg_diff==null?'–':Number(s.xg_diff).toFixed(2)}</td></tr>`};$('#delInsightTeams').innerHTML=teamRow('EBB',ebb,'ebb')+teamRow(oppAbbr,opp,'opp');const rows=[...(ebb?.players||[]).map(x=>({...x,_team:'EBB',_cls:'ebb'})),...(opp?.players||[]).map(x=>({...x,_team:oppAbbr,_cls:'opp'}))].sort((a,b)=>(Number(b.xg_sum)||0)-(Number(a.xg_sum)||0)||String(a.player_name||'').localeCompare(String(b.player_name||''),'de'));$('#delInsightPlayers').innerHTML=rows.map(p=>`<tr><td class="${p._cls}">${esc(p._team)}</td><td>#${esc(p.jersey??'–')} ${esc(p.player_name||'')}</td><td>${pairText(p.passes_completed,p.passes_attempted)}</td><td>${pct(p.pass_pct)}</td><td>${pairText(p.pcw_won,p.pcw_total)}</td><td>${pct(p.pcw_pct)}</td><td>${p.xg_sum==null?'–':Number(p.xg_sum).toFixed(2)}</td><td>${p.blocked_shots??'–'}</td></tr>`).join('')||'<tr><td colspan="8" class="muted">Keine Spielerwerte ableitbar.</td></tr>';const before=ebb?.snapshot_before||opp?.snapshot_before,after=ebb?.snapshot_after||opp?.snapshot_after;$('#delInsightStatus').innerHTML=`<b>Snapshot-Differenz:</b> ${before?esc(new Date(before).toLocaleString('de-DE')):'–'} → ${after?esc(new Date(after).toLocaleString('de-DE')):'–'}. ${ins.method?esc(ins.method):''}`;}\n'''
    if "function renderInsight()" not in text:
        text = replace_once(text, "\n  function renderScoring(){", render_insight + "\n  function renderScoring(){", "render insight function")

    path.write_text(text, encoding="utf-8")


def main() -> int:
    repo = ROOT
    required = [repo / "src/delstats/dashboard.py", repo / "scripts/generate_dashboard.py", repo / ".github/workflows/update-del-data.yml", repo / "site/index.html"]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit("Run this script from the repository root after copying the overlay. Missing: " + ", ".join(missing))
    patch_dashboard(required[0])
    patch_generate(required[1])
    patch_workflow(required[2])
    patch_site(required[3])
    print("DEL Insight patch applied.")
    print("Next: pytest -q")
    print("Then: python scripts/update_del_insight.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
