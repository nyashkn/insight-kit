// L3 eval payload — agent-browser eval --stdin reads this and the result is parsed by renderCheck.ts.
// Returns JSON-serializable object: { url, bodyText (50KB max), svgPathCounts[], bigValues[] }.
JSON.stringify({
  url: location.pathname,
  bodyText: document.body.innerText.slice(0, 50000),
  svgPathCounts: Array.from(document.querySelectorAll('svg')).map(s => s.querySelectorAll('path').length),
  bigValues: Array.from(document.querySelectorAll('.big-value-value, [class*="bigvalue"]')).map(el => el.textContent.trim()).slice(0, 50)
})
