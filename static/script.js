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
      <a href="/team/${team.id}" class="teamRow">
        <strong>${team.name}</strong>
      </a>
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

