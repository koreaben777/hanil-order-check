"""Single-machine set-block sequencing. No ERP, external LLM, or pattern changes."""
from __future__ import annotations

import json
import math
from copy import deepcopy
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

__all__=["schedule"]

# Editable JSON and packaged fallback share these estimated defaults (rule IDs below).
DEFAULT_TRANSITION_RULES = {'color': {'same_h': 0,
           'light_to_dark_h': 0.83,
           'dark_to_light_h': 5.5,
           'dark_to_light_cr_rolls': 6,
           'lightness_order': ['WH',
                               'NT',
                               'UV',
                               'UB',
                               'AW',
                               'CP',
                               'IV',
                               'LA',
                               'LB',
                               'LG',
                               'BE',
                               'YL',
                               'PK',
                               'OR',
                               'GD',
                               'MA',
                               'BR',
                               'RD',
                               'DA',
                               'DG',
                               'DB',
                               'UG',
                               'BK'],
           'estimated': True,
           'comments': {'same_h': '[추정] C-04: identical full color code',
                        'light_to_dark_h': '[추정] C-03: 40-60 minute midpoint, specified 0.83h',
                        'dark_to_light_h': '[추정] C-01/C-02: 5-6 hour midpoint; other descending colors '
                                           'also estimated',
                        'dark_to_light_cr_rolls': '[추정] C-02/C-05: 5-7 roll midpoint, BK->WH only',
                        'lightness_order': '[추정] 관측 계열의 추정 순서, 기준표 수령 시 교체 (C-01/C-04)'}},
 'weight': {'threshold_gsm': 30,
            'drop_h_per_gsm': 0.0375,
            'rise_h_per_gsm': 0,
            'agri_switch_h': 1.0,
            'anchor': '100g→30g 직행 = 1.5h (S-05 경험값 1~2h 중앙값)',
            'estimated': True,
            'comments': {'threshold_gsm': '[추정] S-05: natural cooling threshold, not a measured '
                                          'standard',
                         'drop_h_per_gsm': '[추정] S-05: 1.5h / (70g - 30g)',
                         'rise_h_per_gsm': '[추정] S-04/S-06: no heating-time table; zero baseline',
                         'agri_switch_h': '[추정] S-07: no temperature-reset table',
                         'anchor': '[추정] S-05: calibration example, not validated transition data'}},
 'cr_roll_kg': 100,
 'objective': {'urgent_weight': 10,
               'cr_minutes_per_roll': 60,
               'estimated': True,
               'comments': {'urgent_weight': '[추정] S-08/S-09: unspecified weight, configurable '
                                             'conservative baseline',
                            'cr_minutes_per_roll': '[추정] C-02/C-05: unspecified kappa, configurable 1h '
                                                   'per CR roll'}},
 'estimated': True,
 'comments': {'cr_roll_kg': '[추정] C-06: placeholder 100kg/roll; actual CR specification required'}}


def _datetime(value):
    try:
        if isinstance(value,datetime): return value
        if isinstance(value,date): return datetime.combine(value,datetime.min.time())
        return datetime.fromisoformat(value)
    except (TypeError,ValueError):
        raise ValueError("timestamps must be ISO-8601 dates/datetimes; free-text deadlines require review") from None


def _minute(value,t0,*,ceil=True):
    try: minutes=(_datetime(value)-t0).total_seconds()/60
    except TypeError: raise ValueError("all timestamps must use consistent timezone awareness") from None
    return math.ceil(minutes-1e-9) if ceil else math.floor(minutes+1e-9)


def _finite(value,name,positive=False):
    try:
        n=float(value)
        if isinstance(value,bool) or not math.isfinite(n) or n<0 or (positive and n==0): raise ValueError()
        return n
    except (TypeError,ValueError): raise ValueError(f"invalid {name}") from None


def _jobs(plan_result,t0):
    if not plan_result.get("complete"): raise ValueError("cannot schedule an incomplete plan")
    orders={o["order_id"]:o for o in plan_result["orders"]}
    jobs=[]
    machines={g["machine"] for g in plan_result["groups"] if g["sets"]}
    if len(machines)>1: raise ValueError("one machine per schedule call; split machine 1/2 plans")
    for g in plan_result["groups"]:
        if g["status"] not in ("OPTIMAL","FEASIBLE"): raise ValueError("unsolved plan group")
        hours=_finite(g["production_hours"],"production_hours",True)
        total=_finite(g["mr_length_m"],"mr_length_m",True)
        weight=_finite(g["mr_weight_kg"],"mr_weight_kg",True)
        for s in g["sets"]:
            rows=[orders[i] for i in s["rolls"]]
            dues=[_minute(o["due"],t0,ceil=False) for o in rows if o.get("due")]
            releases=[_minute(o["available_from"],t0) for o in rows if o.get("available_from")]
            share=s["count"]*s["length"]/total
            processing=hours*share
            color=g["item"][-4:]
            jobs.append(dict(job_id=f'{g["item"]}:{s["set_no"]}',item=g["item"],set_no=s["set_no"],
                             machine=g["machine"],color_code=color,gsm=g["gsm"],agri=color[:2] in ("UV","UB"),
                             pattern=s["pattern"],length=s["length"],count=s["count"],rolls=dict(s["rolls"]),
                             duration_minutes=max(1,math.ceil(processing*60-1e-9)),production_hours=processing,
                             due_min=min(dues) if dues else None,release_min=max([0]+releases),
                             urgent=any(o.get("urgent",False) for o in rows),
                             mr_length_m=s["length"]*s["count"],mr_weight_kg=weight*share,
                             mb_kg=None if g.get("mb_kg") is None else g["mb_kg"]*share))
    if len({j["job_id"] for j in jobs})!=len(jobs): raise ValueError("duplicate set job IDs")
    return jobs


def _transition(previous,current,rules):
    """[추정] C-01..C-06, S-04..S-07: raw hours plus safe integer-minute lag."""
    color,weight=rules["color"],rules["weight"]
    a,b=previous["color_code"],current["color_code"]
    families=color["lightness_order"]
    unknown=a[:2] not in families or b[:2] not in families
    cr=0
    if unknown: color_h=color["dark_to_light_h"]
    elif a==b: color_h=color["same_h"]
    elif families.index(a[:2])>families.index(b[:2]): color_h=color["dark_to_light_h"]
    else: color_h=color["light_to_dark_h"]
    if a[:2]=="BK" and b[:2]=="WH": cr=color["dark_to_light_cr_rolls"]
    delta=previous["gsm"]-current["gsm"]
    # [추정] S-05 convex cooling excess; S-04/S-06 heating defaults to zero.
    weight_h=(weight["drop_h_per_gsm"] if delta>0 else weight["rise_h_per_gsm"])*max(0,abs(delta)-weight["threshold_gsm"])
    if previous["agri"]!=current["agri"]: weight_h+=weight["agri_switch_h"]
    hours=color_h+weight_h
    return dict(delta_h=hours,scheduled_minutes=math.ceil(hours*60-1e-9),cr_rolls=cr,
                cr_kg=cr*rules["cr_roll_kg"],rise=int(delta<0),unknown_color=unknown)


def _solve_sequence(jobs,state,transitions,frozen,blocked,rules,*,time_limit):
    """Entire CP-SAT model; no tuning except time limit. Frozen is a fixed prefix."""
    from ortools.sat.python import cp_model
    n=len(jobs)
    if not n: return dict(status="OPTIMAL",order=[],starts=[],ends=[])
    max_delta=max(t["scheduled_minutes"] for t in transitions.values())
    tail=max([0]+[j["release_min"] for j in jobs]+[f["start"] for f in frozen]+[e for _,e in blocked])
    horizon=tail+sum(j["duration_minutes"] for j in jobs)+n*max_delta+1
    model=cp_model.CpModel()
    starts=[model.new_int_var(j["release_min"],horizon,f"start_{i}") for i,j in enumerate(jobs)]
    ends=[model.new_int_var(0,horizon,f"end_{i}") for i in range(n)]
    intervals=[model.new_interval_var(s,j["duration_minutes"],e,f"job_{i}") for i,(s,e,j) in enumerate(zip(starts,ends,jobs))]
    intervals += [model.new_fixed_size_interval_var(s,e-s,f"blocked_{i}") for i,(s,e) in enumerate(blocked)]
    model.add_no_overlap(intervals)
    arcs={}
    for i in range(n+1):
        for j in range(n+1):
            if i==j: continue
            arc=model.new_bool_var(f"arc_{i}_{j}");arcs[i,j]=arc
            if j:
                model.add(starts[j-1]>=(ends[i-1] if i else 0)+transitions[i,j]["scheduled_minutes"]).only_enforce_if(arc)
    model.add_circuit([(i,j,a) for (i,j),a in arcs.items()])
    index={j["job_id"]:i+1 for i,j in enumerate(jobs)}
    previous=0
    for f in frozen:
        node=index[f["job_id"]]
        model.add(starts[node-1]==f["start"])
        model.add(arcs[previous,node]==1)
        previous=node
    tardiness=[]
    for i,j in enumerate(jobs):
        due=j["due_min"]
        t=model.new_int_var(0,horizon+max(0,-due) if due is not None else 0,f"tardy_{i}")
        model.add_max_equality(t,[0,ends[i]-due]) if due is not None else model.add(t==0)
        tardiness.append(t)
    makespan=model.new_int_var(0,horizon,"makespan");model.add_max_equality(makespan,ends)
    costs={key:t["scheduled_minutes"]+rules["objective"]["cr_minutes_per_roll"]*t["cr_rolls"] for key,t in transitions.items()}
    max_cost=n*max(costs.values())
    # Integer lexicographic domination: tardiness >> setup loss >> makespan >> rises.
    w3=n+1
    w2=(horizon+1)*w3
    w1=(max_cost+1)*w2
    model.minimize(w1*sum(t*(rules["objective"]["urgent_weight"] if j["urgent"] else 1) for t,j in zip(tardiness,jobs))
                   +w2*sum(arcs[k]*v for k,v in costs.items())+w3*makespan
                   +sum(arcs[k]*t["rise"] for k,t in transitions.items()))
    if model.validate(): raise ValueError("CP-SAT model integer range exceeded; shorten planning horizon")
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=time_limit
    status=solver.solve(model)
    if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE): return dict(status=solver.status_name(status),order=[],starts=[],ends=[])
    order=[];node=0
    for _ in range(n):
        node=next(j for j in range(1,n+1) if j!=node and solver.value(arcs[node,j]))
        order.append(node-1)
    return dict(status=solver.status_name(status),order=order,starts=[solver.value(s) for s in starts],
                ends=[solver.value(e) for e in ends],objective_value=solver.objective_value,
                objective_bound=solver.best_objective_bound)


def _timeline(jobs,solution,transitions,t0,blocked):
    """Use solved times, never reconstruct a different schedule around downtime."""
    output,changes=[],[];previous=0;previous_end=0
    def stamp(m): return (t0+timedelta(minutes=m)).isoformat()
    for seq,i in enumerate(solution["order"],1):
        j=jobs[i];start,end=solution["starts"][i],solution["ends"][i]
        tr=transitions[previous,i+1]
        if start<previous_end+tr["scheduled_minutes"] or start<j["release_min"] or end!=start+j["duration_minutes"]:
            raise ValueError("schedule time invariant violated")
        if any(start<b and a<end for a,b in blocked): raise ValueError("blocked interval violated")
        tardy=max(0,end-j["due_min"])/60 if j["due_min"] is not None else 0
        output.append({k:v for k,v in j.items() if k not in ("due_min","release_min")}|dict(
            sequence=seq,start=stamp(start),end=stamp(end),due=stamp(j["due_min"]) if j["due_min"] is not None else None,
            available_from=stamp(j["release_min"]),tardiness_h=tardy))
        changes.append(tr|{"from":jobs[previous-1]["job_id"] if previous else "0","to":j["job_id"]})
        previous=i+1;previous_end=end
    return output,changes,stamp(previous_end)


def schedule(plan_result, *, t0, machine_state, frozen=(), blocked=(), rules_file=None,time_limit=30) -> dict:
    """Frozen records: {job_id:'ITEM:set_no',start:ISO[,end:ISO]} in prefix order.

    Blocked records: {start:ISO,end:ISO}. All times use t0 timezone consistently.
    C-02/S-05: report raw estimated hours; integer-minute duration/lag rounds up.
    No optional hard color constraints: defaults remain soft. Changes may overlap
    downtime as formalized (only production intervals participate in NoOverlap).
    """
    t0=_datetime(t0);seconds=_finite(time_limit,"time_limit",True)
    path=Path(rules_file) if rules_file is not None else Path(__file__).with_name("transition_rules.json")
    # Explicit paths fail visibly if missing; only absent adjacent JSON uses fallback.
    rules=json.loads(path.read_text()) if rules_file is not None or path.exists() else deepcopy(DEFAULT_TRANSITION_RULES)
    for section,keys in (("color",("same_h","light_to_dark_h","dark_to_light_h","dark_to_light_cr_rolls")),
                         ("weight",("threshold_gsm","drop_h_per_gsm","rise_h_per_gsm","agri_switch_h")),
                         ("objective",("urgent_weight","cr_minutes_per_roll"))):
        if section not in rules: raise ValueError("missing rules section")
        for key in keys: rules[section][key]=_finite(rules[section].get(key),key)
    rules["cr_roll_kg"]=_finite(rules.get("cr_roll_kg"),"cr_roll_kg",True)
    for section,key in (("color","dark_to_light_cr_rolls"),("objective","urgent_weight"),("objective","cr_minutes_per_roll")):
        value=rules[section][key]
        if value!=int(value) or (key=="urgent_weight" and value<1): raise ValueError("objective weights/CR counts must be integers")
        rules[section][key]=int(value)
    families=rules["color"].get("lightness_order")
    if not isinstance(families,list) or not families or not all(isinstance(c,str) and len(c)==2 for c in families) or len(set(families))!=len(families): raise ValueError("invalid lightness_order")
    if not isinstance(machine_state,dict) or not isinstance(machine_state.get("color_code"),str) or len(machine_state["color_code"])!=4 or not isinstance(machine_state.get("agri"),bool): raise ValueError("machine_state needs color_code, gsm, agri")
    state=dict(machine_state);state["gsm"]=_finite(state.get("gsm"),"machine_state gsm",True)
    jobs=_jobs(plan_result,t0)
    by_id={j["job_id"]:j for j in jobs}
    fixed=[]
    for f in frozen:
        if not isinstance(f,dict) or set(f)-{"job_id","start","end"} or f.get("job_id") not in by_id or "start" not in f: raise ValueError("invalid frozen record")
        start=_minute(f["start"],t0)
        if start<0 or start!=_minute(f["start"],t0,ceil=False): raise ValueError("frozen start must be an exact nonnegative minute from t0")
        if "end" in f and _datetime(f["end"])!=t0+timedelta(minutes=start+by_id[f["job_id"]]["duration_minutes"]): raise ValueError("frozen end differs from processing duration")
        fixed.append(dict(job_id=f["job_id"],start=start))
    if len({f["job_id"] for f in fixed})!=len(fixed): raise ValueError("duplicate frozen job")
    unavailable=[]
    for b in blocked:
        if not isinstance(b,dict) or set(b)!={"start","end"} or _datetime(b["end"])<=_datetime(b["start"]): raise ValueError("invalid blocked interval")
        a,e=_minute(b["start"],t0,ceil=False),_minute(b["end"],t0)
        if e>0: unavailable.append((max(0,a),e))
    merged=[]
    for a,b in sorted(unavailable):
        if merged and a<=merged[-1][1]: merged[-1]=(merged[-1][0],max(merged[-1][1],b))
        else: merged.append((a,b))
    transitions={(i,j):_transition(state if i==0 else jobs[i-1],jobs[j-1],rules)
                 for i in range(len(jobs)+1) for j in range(1,len(jobs)+1) if i!=j}
    warnings=list(plan_result.get("warnings",[]))+["[추정] C-01..C-06/S-04..S-07: transition coefficients",
             "Transition/production intervals round up to integer minutes; delta_h retains raw estimates",
             "[추정] S-08/S-09/C-02: urgent weight and CR minute-equivalent are configurable assumptions"]
    unknown_families=sorted({j["color_code"][:2] for j in [state]+jobs if j["color_code"][:2] not in families})
    if unknown_families:
        warnings.append(f"C-01/C-04: unknown color families {unknown_families}; lightness_order 보완 필요")
    if any(j["mb_kg"] is None for j in jobs): warnings.append("F-04: MB total excludes jobs without mb_ratio")
    solution=_solve_sequence(jobs,state,transitions,fixed,merged,rules,time_limit=seconds)
    complete=solution["status"] in ("OPTIMAL","FEASIBLE")
    timeline,changes,end=_timeline(jobs,solution,transitions,t0,merged)
    mb=defaultdict(float)
    for j in timeline:
        if j["mb_kg"] is not None: mb[j["color_code"]]+=j["mb_kg"]
    return dict(jobs=timeline,transitions=changes,total_changeover_h=sum(t["delta_h"] for t in changes) if complete else None,
                total_scheduled_changeover_minutes=sum(t["scheduled_minutes"] for t in changes) if complete else None,
                total_cr_rolls=sum(t["cr_rolls"] for t in changes) if complete else None,
                total_tardiness_h=sum(j["tardiness_h"] for j in timeline) if complete else None,
                makespan_end=end if complete else None,mb_kg_by_color=dict(mb),status=solution["status"],
                complete=complete,rise_count=sum(t["rise"] for t in changes) if complete else None,
                coefficients_estimated=True,warnings=list(dict.fromkeys(warnings)))
