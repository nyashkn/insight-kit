// Lifted from growth_insights/scripts/preflight_check.py `_L4_EVAL_JS` (preflight L4). Run via agent-browser eval.
(function() {
  var findings = [];
  var bodyText = document.body ? document.body.innerText : '';

  // ---- Check 1: Absurd percentages ----------------------------------------
  // Match numbers with optional thousands separators followed by %
  // e.g. 6,000%  5,160%  500.1%
  var pctRe = /(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*%/g;
  var m;
  while ((m = pctRe.exec(bodyText)) !== null) {
    var raw = m[1].replace(/,/g, '');
    var val = parseFloat(raw);
    if (val > 500 || val < -500) {
      findings.push({
        check: 'absurd_pct',
        snippet: m[0].slice(0, 60),
        location: 'body text near char ' + m.index
      });
    }
  }

  // Negative pct form: -NNN%
  var negPctRe = /(-\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*%/g;
  while ((m = negPctRe.exec(bodyText)) !== null) {
    var rawNeg = m[1].replace(/,/g, '');
    var valNeg = parseFloat(rawNeg);
    if (valNeg < -500) {
      findings.push({
        check: 'absurd_pct',
        snippet: m[0].slice(0, 60),
        location: 'body text (negative) near char ' + m.index
      });
    }
  }

  // ---- Check 2: NaN/null literals ------------------------------------------
  // Build visible text excluding <code> blocks
  var clonedBody = document.body ? document.body.cloneNode(true) : null;
  if (clonedBody) {
    var codeTags = clonedBody.querySelectorAll('code, pre');
    codeTags.forEach(function(el) { el.textContent = ''; });
    var visibleText = clonedBody.innerText || clonedBody.textContent || '';
    var badLiterals = [
      { re: /\bNaN\b/g, label: 'NaN' },
      { re: /\bInfinity\b/g, label: 'Infinity' },
      { re: /\b-Infinity\b/g, label: '-Infinity' },
      { re: /\bnull\b/g, label: 'null' },
      { re: /\bundefined\b/g, label: 'undefined' },
      { re: /\[object Object\]/g, label: '[object Object]' }
    ];
    badLiterals.forEach(function(spec) {
      var hit;
      while ((hit = spec.re.exec(visibleText)) !== null) {
        var ctx = visibleText.slice(Math.max(0, hit.index - 20), hit.index + 30).trim();
        findings.push({
          check: 'nan_null_literal',
          snippet: spec.label + ': ...' + ctx + '...',
          location: 'visible text (excl code) near char ' + hit.index
        });
        break; // one finding per literal type per page is enough
      }
    });
  }

  // ---- Check 3: Empty SVG charts ------------------------------------------
  var chartSvgs = document.querySelectorAll(
    '[class*="echarts"] svg, [class*="chart"] svg, .chart svg, svg.chart'
  );
  chartSvgs.forEach(function(svg, i) {
    var drawn = svg.querySelectorAll('path, rect, circle, line').length;
    if (drawn === 0) {
      findings.push({
        check: 'empty_svg_chart',
        snippet: 'SVG #' + i + ' class=' + (svg.getAttribute('class') || '(none)'),
        location: 'chart container index ' + i
      });
    }
  });

  // ---- Check 4: Console errors (via error badge scan) ---------------------
  // agent-browser does not expose window console capture directly via eval;
  // scan for Evidence error badge elements as a proxy.
  var errBadges = document.querySelectorAll('[class*="error"]');
  errBadges.forEach(function(el, i) {
    var txt = (el.textContent || '').trim();
    if (txt.length > 0 && txt.length < 300) {
      findings.push({
        check: 'error_badge',
        snippet: txt.slice(0, 120),
        location: 'error element #' + i + ' class=' + (el.getAttribute('class') || '')
      });
    }
  });

  // ---- Check 5: Invalid Date literal ---------------------------------------
  if (bodyText.indexOf('Invalid Date') !== -1) {
    var idx = bodyText.indexOf('Invalid Date');
    var ctx5 = bodyText.slice(Math.max(0, idx - 20), idx + 40).trim();
    findings.push({
      check: 'invalid_date',
      snippet: ctx5.slice(0, 80),
      location: 'body text near char ' + idx
    });
  }

  // ---- Check 6: X-axis date monotonicity ----------------------------------
  // For each echarts or chart SVG, extract x-axis tick labels and verify
  // they form a monotonic sequence (all ascending OR all descending).
  var allCharts = document.querySelectorAll(
    '[class*="echarts"] svg, [class*="chart"] svg, .chart svg, svg.chart, .evidence-chart svg'
  );
  allCharts.forEach(function(svg, chartIdx) {
    // Query for text elements in x-axis group (echarts: g.xAxis text, or just text in x-axis context)
    var xAxisGroup = svg.querySelector('g.xAxis');
    var xTickTexts = [];
    if (xAxisGroup) {
      var textEls = xAxisGroup.querySelectorAll('text');
      textEls.forEach(function(el) {
        var txt = (el.textContent || '').trim();
        if (txt.length > 0) {
          xTickTexts.push(txt);
        }
      });
    }

    if (xTickTexts.length >= 3) {
      // Try to parse each label as a date
      var parsedDates = [];
      xTickTexts.forEach(function(label, i) {
        var parsed = null;

        // Try ISO YYYY-MM-DD
        if (/^\d{4}-\d{2}-\d{2}$/.test(label)) {
          parsed = new Date(label);
          if (!isNaN(parsed.getTime())) {
            parsedDates.push({ label: label, ts: parsed.getTime(), idx: i });
            return;
          }
        }

        // Try ISO YYYY-MM
        if (/^\d{4}-\d{2}$/.test(label)) {
          parsed = new Date(label + '-01');
          if (!isNaN(parsed.getTime())) {
            parsedDates.push({ label: label, ts: parsed.getTime(), idx: i });
            return;
          }
        }

        // Try MMM-YY (e.g. Jan-26, Feb-26, Dec-25)
        if (/^[A-Za-z]{3}-\d{2}$/.test(label)) {
          // Parse as month-year; assume 20XX for 2-digit year
          var monthNames = ['jan', 'feb', 'mar', 'apr', 'may', 'jun',
                            'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
          var parts = label.toLowerCase().split('-');
          var mIdx = monthNames.indexOf(parts[0]);
          if (mIdx !== -1) {
            var yy = parseInt(parts[1], 10);
            var yyyy = yy < 50 ? 2000 + yy : 1900 + yy;
            var ts = new Date(yyyy, mIdx, 1).getTime();
            if (!isNaN(ts)) {
              parsedDates.push({ label: label, ts: ts, idx: i });
              return;
            }
          }
        }
      });

      // If >=3 dates parsed, check monotonicity
      if (parsedDates.length >= 3) {
        var isAscending = true;
        var isDescending = true;
        for (var j = 0; j < parsedDates.length - 1; j++) {
          if (parsedDates[j].ts >= parsedDates[j + 1].ts) {
            isAscending = false;
          }
          if (parsedDates[j].ts <= parsedDates[j + 1].ts) {
            isDescending = false;
          }
        }

        if (!isAscending && !isDescending) {
          // Not monotonic
          var dateSeq = parsedDates.map(function(d) { return d.label; }).slice(0, 5).join(', ');
          findings.push({
            check: 'x_axis_date_unsorted',
            snippet: '[' + dateSeq + (parsedDates.length > 5 ? ', ...]' : ']'),
            location: 'chart SVG #' + chartIdx + ' (xAxis text nodes)'
          });
        }
      }
    }
  });

  return JSON.stringify(findings);
})()
