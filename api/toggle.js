export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const token = process.env.GH_TOKEN;
  if (!token) {
    return res.status(500).json({ error: 'GH_TOKEN not configured' });
  }

  try {
    const body = JSON.parse(req.body || '{}');
    const enable = body.enable === true;

    const resp = await fetch(
      `https://api.github.com/repos/garahan/jkk-radar/actions/workflows/scrape.yml/${enable ? 'enable' : 'disable'}`,
      {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
        },
      }
    );

    if (resp.status === 204) {
      res.status(200).json({ ok: true, enabled: enable });
    } else {
      const text = await resp.text();
      res.status(resp.status).json({ error: text });
    }
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}
