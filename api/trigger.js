export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const token = process.env.GH_TOKEN;
  if (!token) {
    return res.status(500).json({ error: 'GH_TOKEN not configured' });
  }

  try {
    const resp = await fetch(
      'https://api.github.com/repos/garahan/jkk-radar/actions/workflows/scrape.yml/dispatches',
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
        },
        body: JSON.stringify({ ref: 'main' }),
      }
    );

    if (resp.status === 204) {
      res.status(200).json({ ok: true, message: 'Scan triggered! Check Telegram in ~2 min.' });
    } else {
      const text = await resp.text();
      res.status(resp.status).json({ error: text });
    }
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}
