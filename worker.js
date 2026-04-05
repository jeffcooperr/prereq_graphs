export default {
  async fetch(request, env, ctx) {
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'POST',
          'Access-Control-Allow-Headers': 'Content-Type',
        }
      });
    }

    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 });
    }

    let auditText;
    try {
      const body = await request.json();
      auditText = body.audit;
    } catch (e) {
      return json({ error: 'Invalid JSON: ' + e.message }, 400);
    }

    if (!auditText || auditText.length < 10) {
      return json({ error: 'No audit text provided' }, 400);
    }

    const prompt = `You are parsing a UVM (University of Vermont) degree audit. Extract ONLY the courses this student has already COMPLETED (passed with a grade). Do NOT include courses that are required but not yet taken, planned, in progress, or waived. Return a JSON array of course codes only, like: ["CS 1210", "MATH 1234", "ENGL 1010"]. Return ONLY the JSON array, no explanation.\n\nDegree audit:\n${auditText}`;

    try {
      console.log('API key present:', !!env.GOOGLE_API_KEY, 'length:', env.GOOGLE_API_KEY?.length);
      const geminiRes = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key=${env.GOOGLE_API_KEY}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }]
        })
      });

      const rawText = await geminiRes.text();
      console.log('Gemini status:', geminiRes.status);
      console.log('Gemini raw:', rawText.slice(0, 500));

      let data;
      try { data = JSON.parse(rawText); }
      catch (e) { return json({ error: 'Gemini returned non-JSON', raw: rawText.slice(0, 300) }, 500); }

      const text = data?.candidates?.[0]?.content?.parts?.[0]?.text;
      if (!text) return json({ error: 'No response from Gemini', raw: data }, 500);

      return new Response(text, {
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    } catch (e) {
      return json({ error: 'Gemini call failed: ' + e.message }, 500);
    }
  }
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
  });
}
