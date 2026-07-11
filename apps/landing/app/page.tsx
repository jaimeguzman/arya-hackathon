export default function Home() {
  return (
    <>
      <nav className="topbar">
        <div className="wrap topbar-inner">
          <div className="wordmark">
            Intake<span>AI</span>
          </div>
          <div className="top-meta">REFERRAL INTAKE · 24/7 · BUILT ON TWILIO</div>
          <div className="top-links">
            <a href="#problem">Problem</a>
            <a href="#process">Process</a>
            <a href="#capabilities">Capabilities</a>
            <a href="#call">Call ticket</a>
          </div>
        </div>
      </nav>

      <header className="hero">
        <div className="wrap hero-grid">
          <div>
            <div className="file-line">
              Referral received · Fri 19:02 · <b>after hours</b> · no staff on
              site
            </div>
            <h1>
              The phone rings at 7&nbsp;PM. <em>Somebody answers.</em>
            </h1>
            <p className="sub">
              IntakeAI takes every referral call, reads every fax, and checks
              service area, insurance, and caregiver availability while the
              discharge planner is still on the line. Answer in three minutes,
              not two hours.
            </p>
            <div className="hero-cta">
              <a className="btn" href="#call">
                Read a live call ticket
              </a>
              <a className="btn secondary" href="#process">
                See the process
              </a>
            </div>
          </div>

          <div className="ticket" id="call">
            <div className="ticket-head">
              <span>
                <span className="live-dot" />
                Call ticket #4127 · inbound
              </span>
              <span>Provider mode</span>
            </div>
            <div className="ticket-body">
              <div className="log-row">
                <span className="t">19:02:41</span>
                <span>
                  <span className="who">Mount Sinai · discharge</span>
                  <span className="say">
                    72 F, hip replacement, discharging tomorrow AM. Skilled
                    nursing 3x/week. Medicare Part A, zip 11201. Can you take
                    her?
                  </span>
                </span>
              </div>
              <div className="log-row sys">
                <span className="t">19:02:44</span>
                <span>
                  <span className="who">Eligibility check · 2.1s</span>
                  <span className="say">
                    zip 11201 OK · Medicare A contracted · dx&rarr;RN + ortho
                    cert · 3 RNs available · F2F note missing
                  </span>
                </span>
              </div>
              <div className="log-row">
                <span className="t">19:02:47</span>
                <span>
                  <span className="who">IntakeAI</span>
                  <span className="say">
                    Yes — we can accept. A nurse is available within 48 hours.
                    We&apos;ll need the face-to-face encounter note; can you fax
                    it over?
                  </span>
                </span>
              </div>
              <div className="log-row sys">
                <span className="t">19:05:12</span>
                <span>
                  <span className="who">Follow-up queued</span>
                  <span className="say">
                    SMS confirmation sent · F2F note chase in 4h if not
                    received
                  </span>
                </span>
              </div>
              <div className="log-row">
                <span className="t">19:05:12</span>
                <span>
                  <span className="who">Call closed</span>
                  <span className="say">Duration 2m 31s · patient retained</span>
                </span>
              </div>
            </div>
            <div className="stamp">ACCEPTED</div>
          </div>
        </div>
      </header>

      <section id="problem">
        <div className="wrap">
          <div className="sec-label">Section A — Why referrals get lost</div>
          <h2>The planner calls five agencies. The fastest one wins.</h2>
          <p className="lede">
            Discharge planners don&apos;t wait for a callback. If the call hits
            voicemail or the answer takes two hours, the patient goes to the
            next agency on the list.
          </p>
          <div className="report">
            <div className="report-row">
              <div className="val">36%</div>
              <div className="desc">
                of referrals never convert — down from a 77% conversion rate in
                2018 to 64% today.
              </div>
            </div>
            <div className="report-row">
              <div className="val">70 min</div>
              <div className="desc">
                for a coordinator to manually read one referral packet before
                anyone can answer.
              </div>
            </div>
            <div className="report-row">
              <div className="val">20%</div>
              <div className="desc">
                of referrals arrive outside business hours, when nobody picks
                up at all.
              </div>
            </div>
            <div className="report-row">
              <div className="val">69 hrs</div>
              <div className="desc">
                median time from referral to start of care — Medicare&apos;s
                quality bar is a first visit within 48.
              </div>
            </div>
            <div className="report-foot">
              Industry-wide cost of referral leakage: est. $200–500M per year.
            </div>
          </div>
        </div>
      </section>

      <section id="process">
        <div className="wrap">
          <div className="sec-label">Section B — One referral, end to end</div>
          <h2>What happens between &ldquo;hello&rdquo; and &ldquo;done.&rdquo;</h2>
          <p className="lede">
            Timestamps from the call above. Every step is a specialized agent;
            the orchestrator keeps them honest.
          </p>
          <div className="proc">
            <div className="proc-row">
              <div className="proc-t">19:02:41</div>
              <h3>Call answered, caller identified</h3>
              <p>
                Twilio ConversationRelay picks up and detects who&apos;s
                calling. A discharge planner gets clinical, structured
                questions; a worried daughter at midnight gets plain language
                and no jargon.
              </p>
            </div>
            <div className="proc-row">
              <div className="proc-t">19:02:44</div>
              <h3>Eligibility checked mid-sentence</h3>
              <p>
                While the caller talks, the eligibility agent walks a Neo4j
                knowledge graph and PostgreSQL: service area, insurance
                contract, diagnosis-to-certification mapping, live caregiver
                availability. Under three seconds, deterministic result:
                ACCEPT, DECLINE, or NEEDS_MORE_INFO.
              </p>
            </div>
            <div className="proc-row">
              <div className="proc-t">any hour</div>
              <h3>Faxes read themselves</h3>
              <p>
                A 50-page packet runs through seven layers: page
                classification, dual-path OCR, then a
                validate–correct–cross-reference loop that catches a smudged
                ICD code or a 50,000&nbsp;mg metformin typo before it enters
                the record. Each field carries a confidence score.
              </p>
            </div>
            <div className="proc-row">
              <div className="proc-t">19:05:12</div>
              <h3>Gaps chased automatically</h3>
              <p>
                Missing face-to-face note? The agent calls the hospital back.
                Unconfirmed address? It calls the family and sends SMS — with
                retries, voicemail handling, and escalation to a human after
                three attempts.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section id="capabilities">
        <div className="wrap">
          <div className="sec-label">Section C — Intake capability checklist</div>
          <h2>Guardrails and domain knowledge are the product.</h2>
          <p className="lede">
            Not a language model guessing at Medicare rules — a knowledge graph
            of real ICD-10 codes, NPI validation, and payer coverage rules,
            wrapped in guardrails enforced in code.
          </p>
          <div className="checklist">
            <div className="check">
              <span className="tick">[x] 24/7 voice intake</span>
              <h3>Every call answered</h3>
              <p>
                Provider, family, and patient modes. Data extracted in real
                time, an answer given before the call ends.
              </p>
            </div>
            <div className="check">
              <span className="tick">[x] Fax pipeline</span>
              <h3>Packets processed in minutes</h3>
              <p>
                High-confidence fields auto-populate; low-confidence fields go
                to the gap list. Nothing enters the record silently.
              </p>
            </div>
            <div className="check">
              <span className="tick">[x] Eligibility engine</span>
              <h3>Deterministic decisions</h3>
              <p>
                ACCEPT / DECLINE / NEEDS_MORE_INFO with specific reasons,
                matched caregivers, and the exact documents still required.
              </p>
            </div>
            <div className="check">
              <span className="tick">[x] Hard guardrails</span>
              <h3>Blocked before speech</h3>
              <p>
                No medical advice, no admission promises before eligibility
                confirms, no full member IDs read aloud. Enforced by code
                before text-to-speech, not by prompt alone.
              </p>
            </div>
            <div className="check">
              <span className="tick">[x] Outbound follow-up</span>
              <h3>The loop closes itself</h3>
              <p>
                Calls, SMS, and email to collect missing documents and schedule
                first visits. Three failed attempts escalate to a coordinator.
              </p>
            </div>
            <div className="check">
              <span className="tick">[x] Live dashboard</span>
              <h3>Every referral visible</h3>
              <p>
                Pipeline status, confidence scores, transcripts, caregiver
                matches, and time-to-decision on one screen.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="closing">
        <div className="wrap">
          <div className="sec-label">Section D — The point</div>
          <h2>
            Speed wins patients. <em>This is speed.</em>
          </h2>
          <p className="lede">
            An agency running IntakeAI never misses a patient because nobody
            picked up the phone — and never loses one because the answer came
            too late.
          </p>
          <div className="hero-cta">
            <a className="btn" href="#call">
              Read the call ticket again
            </a>
          </div>
        </div>
      </section>

      <footer>
        <div className="wrap foot">
          <span>IntakeAI · AI Healthcare Hack NYC</span>
          <span>Twilio · LangGraph · Neo4j · FastAPI</span>
        </div>
      </footer>
    </>
  );
}
