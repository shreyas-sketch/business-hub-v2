import React from "react";
import VoiceNote from "../components/VoiceNote.jsx";
import KitPage from "../kit.jsx";
import { api } from "../api.js"; // used by Reviews
import { Busy, canAct, useHub } from "../ui.jsx"; // used by Reviews

const FUNCTIONS = ["Marketing", "Sales", "Operations", "Product development", "Accounts and finance", "People (HR)", "Management"];

export function Sops() {
  return (
    <KitPage kind="sop" feature="sop_library" readRole="staff" writeRole="manager" kicker="Scale · SOP library" id="SC-04" pillar="Scale"
      title={<>Write it once. Done the same <em>way</em>.</>}
      sub="Describe a process in a line, or talk it through in a voice note. The AI turns it into steps anyone on your team can follow."
      cta="Write the SOP" empty="No SOPs yet. Start with the job you explain most often."
      inputs={[{ key: "process", label: "Which process?", placeholder: "Taking a new order on WhatsApp", required: true },
               { key: "notes", label: "How you do it today (optional)", type: "textarea", placeholder: "Type the steps the way you'd explain them to a new person." }]}
      inputsExtra={(set) => <VoiceNote onText={(t) => set((v) => ({ ...v, notes: (v.notes ? v.notes + "\n" : "") + t }))} />}
      fields={[{ key: "title", label: "Title" }, { key: "purpose", label: "Purpose", type: "textarea", rows: 2 }, { key: "owner_role", label: "Who does it" },
               { key: "when", label: "When to use it" },
               { key: "steps", label: "Steps", type: "objlist", item: "step", fields: [{ key: "title", label: "Step" }, { key: "detail", label: "How", type: "textarea", rows: 2 }] },
               { key: "checklist", label: "Checklist", type: "list" }, { key: "mistakes", label: "Mistakes to avoid", type: "list" }]} />
  );
}

export function Hiring() {
  return (
    <KitPage kind="jd" feature="hiring" readRole="manager" writeRole="manager" kicker="Scale · Hiring" id="SC-07" pillar="Scale"
      title={<>Hire for the role, not the <em>rush</em>.</>}
      sub="Name the role. Get the job post, interview questions with what to listen for, and a scorecard to compare candidates."
      cta="Write the hiring kit" empty="No hiring kits yet."
      inputs={[{ key: "role", label: "Role", placeholder: "Sales executive", required: true },
               { key: "notes", label: "Anything specific (optional)", type: "textarea", placeholder: "Two-wheeler needed, Gujarati speaking, 10am–7pm" }]}
      fields={[{ key: "role", label: "Role" }, { key: "summary", label: "Job post summary", type: "textarea" },
               { key: "responsibilities", label: "Responsibilities", type: "list" }, { key: "requirements", label: "Requirements", type: "list" },
               { key: "kpis", label: "How success is measured", type: "list" },
               { key: "interview_questions", label: "Interview questions", type: "objlist", item: "question", fields: [{ key: "q", label: "Question" }, { key: "look_for", label: "Listen for" }] },
               { key: "scorecard", label: "Scorecard", type: "objlist", item: "criterion", fields: [{ key: "criterion", label: "Criterion" }, { key: "weight", label: "Weight (1–5)", type: "number", min: 1, max: 5 }] },
               { key: "salary_note", label: "Salary note", hint: "Left empty unless you add it." }]} />
  );
}

export function Decisions() {
  return (
    <KitPage kind="decision" feature="decision_log" readRole="owner" writeRole="owner" kicker="Structure · Decision log" id="ST-05" pillar="Structure"
      title={<>Automate, delegate or <em>keep</em>.</>}
      sub="List what you personally do every week. The AI sorts each task and gives you the next step. Track them to done."
      cta="Sort my tasks" empty="List your weekly tasks to start your decision log."
      inputs={[{ key: "tasks", label: "Tasks you do yourself, one per line", type: "textarea", rows: 8, required: true,
                 placeholder: "Reply to every WhatsApp inquiry\nMake quotations\nCollect payments\nPost on Instagram\nCheck stock" }]}
      fields={[{ key: "items", label: "Decisions", type: "objlist", item: "task", fields: [
        { key: "task", label: "Task" },
        { key: "verdict", label: "Decision", type: "select", options: [["automate", "Automate"], ["delegate", "Delegate"], ["keep", "Keep"]] },
        { key: "reason", label: "Why" }, { key: "next_step", label: "Next step" },
        { key: "status", label: "Status", type: "select", options: [["todo", "To do"], ["doing", "Doing"], ["done", "Done"]] }] }]} />
  );
}

export function Roles() {
  return (
    <KitPage kind="role" feature="role_clarity" readRole="staff" writeRole="owner" kicker="Structure · Role clarity" id="ST-06" pillar="Structure"
      title={<>Everyone can answer at <em>3am</em>.</>}
      sub="One page per role: what it's for, three or four responsibilities, the tasks for each in order, and how it's measured. Draft it, review it with the person, save each version."
      cta="Write the role" empty="No roles yet. Start with the person who handles your customers."
      inputs={[{ key: "role", label: "Role", placeholder: "Telecaller", required: true }, { key: "person_name", label: "Person in this role (optional)" },
               { key: "function", label: "Business function", type: "select", options: FUNCTIONS },
               { key: "notes", label: "What they do today (optional)", type: "textarea" }]}
      fields={[{ key: "title", label: "Role title" }, { key: "person_name", label: "Person" },
               { key: "function", label: "Function", type: "select", options: FUNCTIONS.map((f) => [f, f]) },
               { key: "level", label: "Level", type: "select", options: [["creator", "Creator — sets goals and strategy"], ["manager", "Manager — plans and reviews"], ["doer", "Doer — executes"]] },
               { key: "definition", label: "Role definition", type: "textarea", rows: 2 },
               { key: "responsibilities", label: "Responsibilities (max 4)", type: "objlist", item: "responsibility", fields: [{ key: "name", label: "Responsibility" }, { key: "tasks", label: "Tasks, in order", type: "list" }] },
               { key: "metrics", label: "How it's measured", type: "list" }, { key: "reports_to", label: "Reports to" },
               { key: "version", label: "Version", type: "number", min: 1, max: 20, hint: "1 self · 2 team feedback · 3 manager · 4 owner" }]} />
  );
}

const HEADINGS = [["relationships", "When relationships turn resistant"], ["energy", "When energy goes down"], ["commitment", "When commitment becomes conditional"], ["performance", "When performance is full of reasons"]];

export function Culture() {
  return (
    <KitPage kind="culture" feature="culture_plan" readRole="staff" writeRole="owner" kicker="Structure · Culture charter" id="ST-07" pillar="Structure"
      title={<>Our way. Not our <em>way</em>.</>}
      sub="List the situations where things go wrong at work. For each, agree how your team handles it — and how it doesn't. Put it on the wall."
      cta="Draft our charter" empty="No charter yet."
      inputs={[{ key: "notes", label: "Situations you've seen (optional)", type: "textarea", rows: 6, placeholder: "People gossip about each other\nDeliveries get delayed and nobody tells the customer\nThe team is idle in slow weeks" }]}
      fields={[{ key: "name", label: "Name of your way" }, { key: "purpose", label: "In one line", type: "textarea", rows: 2 },
               { key: "situations", label: "Situations", type: "objlist", item: "situation", fields: [
                 { key: "heading", label: "Heading", type: "select", options: HEADINGS }, { key: "situation", label: "Situation" },
                 { key: "our_way", label: "Our way", type: "textarea", rows: 2 }, { key: "not_our_way", label: "Not our way", type: "textarea", rows: 2 }] }]} />
  );
}

export function Competence() {
  return (
    <KitPage kind="competence" feature="competence_plan" readRole="staff" writeRole="owner" kicker="Structure · Competence" id="ST-08" pillar="Structure"
      title={<>Grow the people, grow the <em>results</em>.</>}
      sub="For each role: the skills, knowledge, self-image, traits and motives it needs — and a plan to build them from people, resources and experiences."
      cta="Write the plan" empty="No competence plans yet."
      inputs={[{ key: "role", label: "Role", placeholder: "Site supervisor", required: true }, { key: "notes", label: "Gaps you see (optional)", type: "textarea" }]}
      fields={[{ key: "role", label: "Role" },
               { key: "attributes", label: "What the role needs", type: "group", fields: [
                 { key: "skills", label: "Skills", type: "list" }, { key: "knowledge", label: "Knowledge", type: "list" }, { key: "self_image", label: "Self-image", type: "list" },
                 { key: "traits", label: "Traits", type: "list" }, { key: "motives", label: "Motives", type: "list" }] },
               { key: "plan", label: "Development plan", type: "objlist", item: "row", fields: [
                 { key: "attribute", label: "To build" }, { key: "people", label: "People to learn from" }, { key: "resources", label: "Resources" },
                 { key: "experiences", label: "Experiences" }, { key: "by_when", label: "By when" }] }]} />
  );
}

export function Reviews() {
  const { me, toast, refresh } = useHub();
  const [version, setVersion] = React.useState(0);  // a new key remounts the list, so the new review loads and opens
  const about = "On the 1st of every month the review agent reads your leads, customers, goals, money owed and tasks, and writes an honest review with next steps.";
  const canRun = canAct(me, "owner") && me?.features?.monthly_review;
  const sub = !canRun ? about : (
    <>{about}<span style={{ display: "block", marginTop: 14 }}>
      <Busy className="btn primary" run={async () => {
        await api("/agents/monthly_review/run", { method: "POST" });
        toast("This month's review is ready");
        refresh();
        setVersion((v) => v + 1);
      }}>Write this month's review now</Busy>
      <span className="small muted" style={{ marginLeft: 12 }}>Uses one AI run.</span>
    </span></>
  );
  return (
    <KitPage key={version} kind="review" feature="monthly_review" readRole="manager" writeRole="owner" kicker="Scale · Monthly review" id="SC-09" pillar="Scale"
      title={<>Is the business getting <em>better</em>?</>}
      sub={sub} lockedWhat={about}
      cta="Write this month's review now" empty="Your first review arrives on the 1st. Or write one now."
      canCreate={false}
      inputs={[]}
      fields={[{ key: "headline", label: "Headline" }, { key: "numbers", label: "Numbers", type: "keyvalue" }, { key: "wins", label: "What went well", type: "list" },
               { key: "concerns", label: "Needs attention", type: "list" },
               { key: "recommendations", label: "Next steps", type: "objlist", item: "step", fields: [{ key: "action", label: "Action" }, { key: "why", label: "Why" }] },
               { key: "focus_next_month", label: "Focus next month", type: "textarea", rows: 2 }]} />
  );
}
