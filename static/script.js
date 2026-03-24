function renderMatches(title, matches) {
  let html = `<div class="section"><h2>${title}</h2>`;

  if (!matches || matches.length === 0) {
    html += `<p class="message">No matches found.</p></div>`;
    return html;
  }

  matches.forEach(function(m) {
    const ft = (m.score && m.score.fullTime) ? m.score.fullTime : {};
    const score = (ft.home == null || ft.away == null) ? "TBD" : `${ft.home} - ${ft.away}`;

    const date = new Date(m.utcDate);
    const formattedDate = date.toLocaleDateString();

    html += `
      <div class="match-card">
        <div class="match-date">${formattedDate}</div>
        <div class="match-title">
          ${m.homeTeam.name} vs ${m.awayTeam.name}
          ${score !== "TBD" ? ` | ${score}` : ""}
        </div>
        <div class="match-meta">Status: ${m.status}</div>
      </div>
    `;
  });

  html += `</div>`;
  return html;
}

$("#searchForm").submit(function(event) {
  event.preventDefault();

  const teamName = $("#searchInput").val().trim();
  if (!teamName) {
    $("#results").html(`
      <div class="section">
        <h2>Search Results</h2>
        <p class="message error">Please enter a team name.</p>
      </div>
    `);
    return;
  }

  $("#valueBets").html(`
    <div class="section">
      <h2>Value Bets</h2>
      <p class="message">Upcoming value bet opportunities will appear here.</p>
    </div>
  `);

  $.get("/search", { name: teamName }, function(teams) {
    let html = `<div class="section"><h2>Search Results</h2>`;

    if (teams.length === 0) {
      html += `<p class="message">No teams found.</p></div>`;
      $("#results").html(html);
      return;
    }

    teams.forEach(function(team) {
      html += `
        <div class="teamRow" data-teamid="${team.id}">
          <strong>${team.name}</strong>
        </div>
      `;
    });

    html += `</div>`;
    $("#results").html(html);
  }).fail(function() {
    $("#results").html(`
      <div class="section">
        <h2>Search Results</h2>
        <p class="message error">Error searching for teams.</p>
      </div>
    `);
  });
});

$(document).on("click", ".teamRow", function() {
  const teamId = $(this).data("teamid");

  $("#results").html(`
    <div class="section">
      <h2>Matches</h2>
      <p class="message">Loading previous and upcoming matches...</p>
    </div>
  `);

  $("#valueBets").html(`
    <div class="section">
      <h2>Value Bets</h2>
      <p class="message">Loading value bets...</p>
    </div>
  `);

  const last5Req = $.get(`/team/${teamId}/last5`);
  const next5Req = $.get(`/team/${teamId}/next5`);
  const valueReq = $.get(`/team/${teamId}/value_simple`);

  $.when(last5Req, next5Req, valueReq).done(function(last5Res, next5Res, valueRes) {
    const last5 = last5Res[0];
    const next5 = next5Res[0];
    const valueData = valueRes[0];

    let html = "";
    html += renderMatches("Previous 5 Matches (Played)", last5);
    html += renderMatches("Next 5 Matches (Upcoming)", next5);
    $("#results").html(html);

    let vhtml = `<div class="section"><h2>Value Bets (Upcoming)</h2>`;

    if (!valueData || valueData.length === 0) {
      vhtml += `<p class="message">No value bet data found.</p></div>`;
      $("#valueBets").html(vhtml);
      return;
    }

    valueData.forEach(item => {
      if (!item.oddsFound) {
        vhtml += `
          <div class="value-card">
            <strong>${item.match.homeTeam.name} vs ${item.match.awayTeam.name}</strong>
            <p class="message">No odds found for this match.</p>
          </div>
        `;
        return;
      }

      const m = item.match;
      const odds = item.bestOdds;
      const prob = item.modelProb;
      const val = item.value;

      vhtml += `
        <div class="value-card">
          <strong>${m.homeTeam.name} vs ${m.awayTeam.name}</strong>
          <div class="value-grid">
            <div class="stat-box">
              <div class="stat-label">Odds (Home / Draw / Away)</div>
              <div class="stat-value">${odds.home} / ${odds.draw} / ${odds.away}</div>
            </div>
            <div class="stat-box">
              <div class="stat-label">Model Prob (Home / Away)</div>
              <div class="stat-value">${prob.home} / ${prob.away}</div>
            </div>
            <div class="stat-box">
              <div class="stat-label">Value (Home / Away)</div>
              <div class="stat-value">${val.home} / ${val.away}</div>
            </div>
          </div>
        </div>
      `;
    });

    vhtml += `</div>`;
    $("#valueBets").html(vhtml);

  }).fail(function() {
    $("#results").html(`
      <div class="section">
        <h2>Matches</h2>
        <p class="message error">Error loading matches.</p>
      </div>
    `);

    $("#valueBets").html(`
      <div class="section">
        <h2>Value Bets</h2>
        <p class="message error">Error loading value bets.</p>
      </div>
    `);
  });
});