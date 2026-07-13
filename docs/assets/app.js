const state = { jobs: [], filter: "all", query: "", activeKey: null };
const storageKey = "where-is-my-job:application-notes:v1";
const $ = (selector) => document.querySelector(selector);
const localChanges = () => { try { return JSON.parse(localStorage.getItem(storageKey)) || {}; } catch { return {}; } };
const saveChanges = (changes) => localStorage.setItem(storageKey, JSON.stringify(changes));

function dateText(value) {
  if (!value) return "마감일 미정";
  const date = new Date(value); if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", { month: "short", day: "numeric" }).format(date);
}
function deadline(value) {
  if (!value) return { text: "마감일 미정", className: "" };
  const end = new Date(value); if (Number.isNaN(end.getTime())) return { text: value, className: "" };
  const days = Math.ceil((end.setHours(23,59,59,999) - new Date().setHours(0,0,0,0)) / 86400000);
  if (days < 0) return { text: "마감", className: "ended" };
  return { text: days === 0 ? "D-day" : `D-${days}`, className: days <= 7 ? "soon" : "" };
}
function escaped(value = "") { const element = document.createElement("span"); element.textContent = value; return element.innerHTML; }
function currentJobs() { return state.jobs.map(job => ({ ...job, ...(localChanges()[job.job_key] || {}) })); }
function render() {
  const jobs = currentJobs();
  const visible = jobs.filter(job => {
    const matchesFilter = state.filter === "all" || job.status === state.filter;
    const q = state.query.toLowerCase();
    const haystack = [job.company, job.title, job.position, job.location, job.source, job.matched_keywords?.join(" ")].join(" ").toLowerCase();
    return matchesFilter && haystack.includes(q);
  });
  $("#allCount").textContent = jobs.length;
  $("#filterAll").textContent = jobs.length;
  $("#activeCount").textContent = jobs.filter(job => ["관심", "지원완료", "서류합격", "면접중"].includes(job.status)).length;
  $("#closingCount").textContent = jobs.filter(job => { const day = deadline(job.deadline); return day.className === "soon"; }).length;
  $("#listCount").textContent = `${visible.length}개의 공고`;
  const list = $("#jobList");
  list.innerHTML = visible.map(job => {
    const due = deadline(job.deadline);
    return `<article class="job"><div class="job-meta"><strong>${escaped(job.company || "기업 정보 없음")}</strong><span class="deadline ${due.className}">${due.text} · ${dateText(job.deadline)}</span></div><div><h2 class="job-title">${escaped(job.title || job.position || "채용 공고")}</h2><span class="job-location">${escaped(job.location || "근무지 미정")}</span></div><div class="job-role"><span>${escaped(job.position || "직무 미정")}</span><span>${escaped(job.source || "공식 채용 페이지")}</span></div><span class="tag" data-status="${escaped(job.status)}">${escaped(job.status)}</span><button class="manage" type="button" data-key="${escaped(job.job_key)}" aria-label="${escaped(job.title)} 관리">+</button></article>`;
  }).join("");
  $("#emptyState").hidden = visible.length !== 0;
}
function openDialog(key) {
  const job = currentJobs().find(item => item.job_key === key); if (!job) return;
  state.activeKey = key; $("#dialogTitle").textContent = job.title || job.position || "채용 공고"; $("#dialogCompany").textContent = job.company || "기업 정보 없음";
  $("#statusSelect").value = job.status || "신규"; $("#memoInput").value = job.memo || ""; $("#detailLink").href = job.url || "#"; $("#manageDialog").showModal();
}
async function loadJobs() {
  try { const response = await fetch("data/jobs.json", { cache: "no-store" }); if (!response.ok) throw new Error(); const data = await response.json(); state.jobs = data.jobs || []; $("#updatedAt").textContent = data.generated_at ? new Date(data.generated_at).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" }) : "수집 대기 중"; }
  catch { $("#updatedAt").textContent = "데이터를 불러오지 못했어요"; }
  render();
}
$("#search").addEventListener("input", event => { state.query = event.target.value.trim(); render(); });
$("#filters").addEventListener("click", event => { const button = event.target.closest("[data-filter]"); if (!button) return; state.filter = button.dataset.filter; document.querySelectorAll(".filter").forEach(item => item.classList.toggle("active", item === button)); render(); });
$("#jobList").addEventListener("click", event => { const button = event.target.closest(".manage"); if (button) openDialog(button.dataset.key); });
$("#manageForm").addEventListener("submit", () => { if (!state.activeKey) return; const all = localChanges(); all[state.activeKey] = { status: $("#statusSelect").value, memo: $("#memoInput").value.trim() }; saveChanges(all); render(); });
$("#downloadButton").addEventListener("click", () => { const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), changes: localChanges() }, null, 2)], { type: "application/json" }); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = "where-is-my-job-notes.json"; link.click(); URL.revokeObjectURL(link.href); });
loadJobs();
