// S14 · Receipts. The decision log fills in: the desk's proposal arrives first, then the owner's
// approval slides in on top and pushes it down; the ring walks the actor tags (owner, then desk).
import { caption, shot, A, principleTag } from "../lib.js";
import { style, px, pad, dims, cover, piece, glideRing, cue } from "./_polishB.js";

const D = "shot-11-decision-log.png";

export default {
  id: "S14",
  label: "Receipts",
  build(k) {
    style(k);
    const APPROVAL = A(D, "approval_entry", px(D, [37, 112, 413, 134]));
    const PROPOSAL = A(D, "proposal_entry", px(D, [37, 258, 413, 154]));
    const TAG_OWNER = px(D, [36, 134, 152, 17]), TAG_DESK = px(D, [36, 279, 142, 17]);
    const s = shot(k, D, { x: 510, y: 64, w: 900, h: 760, chip: "Fictional shop" });
    k.tween(s.win, { y: [24, 0] }, { at: 0, dur: 0.7 });
    s.set([0, 0.0, 1, 0.9], { z: 1 });
    s.focus([0, 0.06, 1, 0.86], 0.2, k.dur - 0.2, { z: 1.06, ease: "linear" });   // a slow push-in on the entries

    // Both entries start hidden; each is its own pixels sliding into place.
    const { H } = dims(s, D);
    cover(k, s, D, pad([APPROVAL[0], APPROVAL[1], APPROVAL[2], PROPOSAL[1] + PROPOSAL[3] - APPROVAL[1]], 0.01, 0.004));
    const prop = piece(k, s, D, PROPOSAL), appr = piece(k, s, D, APPROVAL);
    const up = (PROPOSAL[1] - APPROVAL[1]) * H;     // the proposal first sits in the top slot
    const t1 = k.v(0.06), t2 = k.v(0.46);
    k.tween(prop, { opacity: [0, 1], y: [-up - 24, -up] }, { at: t1, dur: 0.55 });
    cue(k, "tick", t1);
    k.tween(prop, { y: [-up, 0] }, { at: t2, dur: 0.6, ease: "move" });
    k.tween(appr, { opacity: [0, 1], y: [-28, 0] }, { at: t2 + 0.3, dur: 0.5 });
    cue(k, "tick", t2 + 0.3);

    // Who decided: owner, then desk.
    const ring = glideRing(k, s);
    ring.on(TAG_OWNER, k.v(0.7));
    ring.hop(TAG_DESK, k.v(0.7) + 0.7);
    caption(k, "Every decision logged *with its reasons*", k.v(0.05), null);
    principleTag(k, 4);
  }};
