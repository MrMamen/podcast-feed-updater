<?xml version="1.0" encoding="UTF-8"?>
<!--
  Renders podcast RSS feeds as a readable HTML page when opened in a browser.
  Applied via the <?xml-stylesheet?> processing instruction added by
  src/common/stylesheet.py. Podcast apps ignore the instruction entirely.

  Doubles as a debugging view: every element is visible either in the pretty
  layout or in the collapsible "Alle felter" raw dump per episode/channel,
  so new tags show up automatically without touching this stylesheet.

  Written in XSLT 1.0 so it also works with lxml's etree.XSLT, which can take
  over the transformation at build time if browsers drop native XSLT support.
  Note: disable-output-escaping (used to render description HTML) works in
  Chrome/Safari/lxml but not in Firefox, which shows the raw HTML as text.
-->
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:podcast="https://podcastindex.org/namespace/1.0"
    xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
    exclude-result-prefixes="podcast itunes">

  <xsl:output method="html" encoding="utf-8"/>

  <!-- Only flag missing persons/chapters in feeds that have them at all -->
  <xsl:variable name="hasPersons" select="boolean(//item/podcast:person)"/>
  <xsl:variable name="hasChapters" select="boolean(//item/podcast:chapters)"/>

  <!-- Aggregated list feeds (built by the list builder, with one season per
       event/edition) get a season-sectioned layout instead of a flat list.
       Regular podcasts keep the flat reverse-chronological view. -->
  <xsl:key name="items-by-season" match="item" use="podcast:season"/>
  <xsl:variable name="listFeed" select="contains(/rss/channel/generator, 'list builder')"/>
  <xsl:variable name="grouped" select="$listFeed and boolean(//item/podcast:season)"/>

  <xsl:template match="/">
    <html lang="no">
      <head>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <title><xsl:value-of select="rss/channel/title"/></title>
        <style>
          body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem;
                 padding: 0 1rem; color: #1a1a1a; background: #fafafa; }
          header { display: flex; gap: 1.2rem; align-items: center; }
          header img.cover { width: 110px; height: 110px; border-radius: 10px; object-fit: cover; }
          h1 { font-size: 1.4rem; margin: 0 0 .3rem; }
          h2 { font-size: 1.05rem; margin: 0 0 .3rem; }
          .desc { color: #333; font-size: .9rem; }
          .desc p { margin: .4rem 0; }
          .subscribe { background: #eef4ff; border: 1px solid #c9dcff; border-radius: 8px;
                       padding: .6rem 1rem; margin: 1rem 0; font-size: .85rem; }
          .channel-links { font-size: .85rem; margin: .5rem 0; }
          .channel-links a + a:before { content: " · "; color: #1a1a1a; }
          .count { color: #555; font-size: .85rem; }
          .episode { background: #fff; border: 1px solid #ddd; border-radius: 8px;
                     padding: 1rem 1.2rem; margin-bottom: 1rem; }
          .ep-head { display: flex; gap: .8rem; align-items: flex-start; }
          .ep-head img { width: 120px; height: 120px; border-radius: 8px; object-fit: cover; }
          .meta { color: #555; font-size: .85rem; margin-bottom: .3rem; }
          .meta span + span:before { content: " · "; }
          .warn { color: #a33; font-size: .8rem; }
          .badge { display: inline-block; border-radius: 4px; padding: .05rem .4rem;
                   font-size: .75rem; background: #e8e8e8; }
          .badge.host { background: #d2e7ff; }
          .badge.guest { background: #d8f5d0; }
          .badge.missing { background: #ffd9d9; }
          .badge.explicit { background: #ffd9d9; }
          .badge.source { background: #eadff7; }
          .season-head { display: flex; align-items: center; gap: .8rem;
                         font-size: 1.15rem; margin: 1.6rem 0 .6rem;
                         padding-bottom: .35rem; border-bottom: 2px solid #ccc; }
          .season-head img { width: 96px; height: 96px; border-radius: 10px;
                             object-fit: cover; }
          .person { display: inline-flex; align-items: center; gap: .4rem; background: #fff;
                    border: 1px solid #ddd; border-radius: 999px; font-size: .85rem;
                    padding: .15rem .6rem .15rem .2rem; margin: 0 .4rem .4rem 0; }
          .person img { width: 28px; height: 28px; border-radius: 50%; object-fit: cover; }
          .person .noimg { width: 28px; height: 28px; border-radius: 50%; background: #eee;
                           display: inline-flex; align-items: center; justify-content: center;
                           font-size: .8rem; color: #888; }
          audio { width: 100%; margin: .4rem 0; }
          .links { font-size: .85rem; }
          .links a + a:before { content: " · "; color: #1a1a1a; }
          details.tech { margin-top: .6rem; font-size: .78rem; }
          details.tech summary { color: #777; cursor: pointer; }
          table.fields { border-collapse: collapse; margin-top: .3rem; width: 100%; }
          table.fields td { border: 1px solid #e3e3e3; padding: .2rem .5rem;
                            vertical-align: top; word-break: break-word; }
          td.fieldname, .subfield .fieldname { font-family: monospace; color: #555;
                                               white-space: nowrap; }
          .attr { font-family: monospace; color: #886a00; }
          .subfield { margin: .1rem 0 .1rem .8rem; }
        </style>
      </head>
      <body>
        <xsl:apply-templates select="rss/channel"/>
      </body>
    </html>
  </xsl:template>

  <xsl:template match="channel">
    <header>
      <xsl:if test="image/url">
        <img class="cover" src="{image/url}" alt=""/>
      </xsl:if>
      <div>
        <h1><xsl:value-of select="title"/></h1>
        <div class="meta">
          <xsl:if test="itunes:author"><span><xsl:value-of select="itunes:author"/></span></xsl:if>
          <xsl:if test="language"><span><xsl:value-of select="language"/></span></xsl:if>
          <xsl:if test="itunes:type"><span><xsl:value-of select="itunes:type"/></span></xsl:if>
          <xsl:if test="itunes:explicit = 'true'">
            <span><span class="badge explicit">explicit</span></span>
          </xsl:if>
        </div>
        <div class="desc">
          <xsl:value-of select="description" disable-output-escaping="yes"/>
        </div>
        <div class="channel-links">
          <xsl:if test="link"><a href="{link}">Nettside</a></xsl:if>
          <xsl:if test="podcast:funding">
            <a href="{podcast:funding/@url}"><xsl:value-of select="podcast:funding"/></a>
          </xsl:if>
          <xsl:for-each select="podcast:socialInteract[@uri]">
            <a href="{@uri}">
              <xsl:choose>
                <xsl:when test="contains(@uri, 'bsky.app')">Bluesky</xsl:when>
                <xsl:when test="contains(@uri, 'facebook.com')">Facebook</xsl:when>
                <xsl:when test="contains(@uri, 'x.com') or contains(@uri, 'twitter.com')">X</xsl:when>
                <xsl:when test="contains(@uri, 'mastodon')">Mastodon</xsl:when>
                <xsl:when test="@accountId"><xsl:value-of select="@accountId"/></xsl:when>
                <xsl:otherwise>
                  <xsl:value-of select="substring-before(substring-after(@uri, '://'), '/')"/>
                </xsl:otherwise>
              </xsl:choose>
            </a>
          </xsl:for-each>
        </div>
      </div>
    </header>
    <div class="subscribe">
      Dette er en podkast-feed (RSS). Kopier adressen fra adressefeltet inn i
      podkastspilleren din for å abonnere. Spillere med Podcasting 2.0-støtte
      viser også medvirkende og kapitler.
    </div>
    <xsl:if test="podcast:person">
      <p>Faste medvirkende:<br/>
        <xsl:apply-templates select="podcast:person"/>
      </p>
    </xsl:if>
    <details class="tech">
      <summary>Alle kanalfelter</summary>
      <table class="fields">
        <xsl:apply-templates mode="raw" select="*[not(self::item or self::title
            or self::description or self::podcast:guid)]"/>
      </table>
    </details>
    <p class="count"><xsl:value-of select="count(item)"/> episoder</p>
    <xsl:choose>
      <xsl:when test="$grouped">
        <!-- One section per distinct season, oldest event first;
             episodes keep the curated running order within each section. -->
        <xsl:for-each select="item[generate-id()
            = generate-id(key('items-by-season', podcast:season)[1])]">
          <xsl:sort select="podcast:season" data-type="number"/>
          <h2 class="season-head">
            <xsl:if test="podcast:season/@image">
              <img src="{podcast:season/@image}" alt="" loading="lazy"/>
            </xsl:if>
            <xsl:choose>
              <xsl:when test="podcast:season/@name">
                <xsl:value-of select="podcast:season/@name"/>
              </xsl:when>
              <xsl:otherwise>Sesong <xsl:value-of select="podcast:season"/></xsl:otherwise>
            </xsl:choose>
          </h2>
          <xsl:apply-templates select="key('items-by-season', podcast:season)"/>
        </xsl:for-each>
        <xsl:apply-templates select="item[not(podcast:season)]"/>
      </xsl:when>
      <xsl:otherwise>
        <xsl:apply-templates select="item"/>
      </xsl:otherwise>
    </xsl:choose>
  </xsl:template>

  <xsl:template match="item">
    <div class="episode">
      <div class="ep-head">
        <xsl:if test="itunes:image/@href">
          <img src="{itunes:image/@href}" alt="" loading="lazy"/>
        </xsl:if>
        <div>
          <h2><xsl:value-of select="title"/></h2>
          <div class="meta">
            <span><xsl:value-of select="pubDate"/></span>
            <xsl:if test="$listFeed and itunes:author[. != /rss/channel/itunes:author]">
              <span><span class="badge source"><xsl:value-of select="itunes:author"/></span></span>
            </xsl:if>
            <xsl:if test="podcast:season and not($grouped)">
              <span>
                <xsl:text>Sesong </xsl:text>
                <xsl:value-of select="podcast:season"/>
                <xsl:if test="podcast:season/@name">
                  <xsl:text> (</xsl:text><xsl:value-of select="podcast:season/@name"/><xsl:text>)</xsl:text>
                </xsl:if>
              </span>
            </xsl:if>
            <xsl:choose>
              <xsl:when test="podcast:episode/@display">
                <span>Episode <xsl:value-of select="podcast:episode/@display"/></span>
              </xsl:when>
              <xsl:when test="itunes:episode">
                <span>Episode <xsl:value-of select="itunes:episode"/></span>
              </xsl:when>
            </xsl:choose>
            <xsl:if test="itunes:episodeType[. != 'full']">
              <span><xsl:value-of select="itunes:episodeType"/></span>
            </xsl:if>
            <xsl:if test="itunes:duration">
              <span>
                <xsl:choose>
                  <xsl:when test="contains(itunes:duration, ':')">
                    <xsl:value-of select="itunes:duration"/>
                  </xsl:when>
                  <xsl:otherwise>
                    <xsl:value-of select="floor(itunes:duration div 60)"/>
                    <xsl:text> min</xsl:text>
                  </xsl:otherwise>
                </xsl:choose>
              </span>
            </xsl:if>
            <xsl:if test="itunes:explicit = 'true'">
              <span><span class="badge explicit">explicit</span></span>
            </xsl:if>
          </div>
          <xsl:if test="itunes:title and itunes:title != title">
            <div class="warn">itunes:title avviker: «<xsl:value-of select="itunes:title"/>»</div>
          </xsl:if>
        </div>
      </div>
      <div class="desc">
        <xsl:value-of select="description" disable-output-escaping="yes"/>
      </div>
      <xsl:choose>
        <xsl:when test="podcast:person">
          <div><xsl:apply-templates select="podcast:person"/></div>
        </xsl:when>
        <xsl:when test="$hasPersons">
          <div><span class="badge missing">ingen personer</span></div>
        </xsl:when>
      </xsl:choose>
      <xsl:if test="enclosure/@url">
        <audio controls="controls" preload="none" src="{enclosure/@url}"></audio>
      </xsl:if>
      <div class="links">
        <xsl:if test="link">
          <a href="{link}">Artikkel</a>
        </xsl:if>
        <xsl:if test="podcast:chapters">
          <a href="{podcast:chapters/@url}">Kapitler</a>
        </xsl:if>
        <xsl:for-each select="podcast:transcript">
          <a href="{@url}">
            <xsl:text>Transkript</xsl:text>
            <xsl:if test="@language"> (<xsl:value-of select="@language"/>)</xsl:if>
          </a>
        </xsl:for-each>
        <xsl:if test="not(podcast:chapters) and $hasChapters">
          <span class="badge missing">ingen kapitler</span>
        </xsl:if>
      </div>
      <details class="tech">
        <summary>Alle felter</summary>
        <table class="fields">
          <xsl:apply-templates mode="raw" select="*[not(self::title or self::description
              or self::guid)]"/>
        </table>
      </details>
    </div>
  </xsl:template>

  <!-- Generic raw dump: element name, attributes, text, one level of children.
       Keeps every tag inspectable without stylesheet changes. -->
  <xsl:template match="*" mode="raw">
    <tr>
      <td class="fieldname"><xsl:value-of select="name()"/></td>
      <td>
        <xsl:for-each select="@*">
          <span class="attr"><xsl:value-of select="name()"/>="<xsl:value-of select="."/>"</span>
          <xsl:text> </xsl:text>
        </xsl:for-each>
        <xsl:choose>
          <xsl:when test="*">
            <xsl:for-each select="*">
              <div class="subfield">
                <span class="fieldname"><xsl:value-of select="name()"/></span>
                <xsl:text> </xsl:text>
                <xsl:for-each select="@*">
                  <span class="attr"><xsl:value-of select="name()"/>="<xsl:value-of select="."/>"</span>
                  <xsl:text> </xsl:text>
                </xsl:for-each>
                <xsl:value-of select="normalize-space(.)"/>
              </div>
            </xsl:for-each>
          </xsl:when>
          <xsl:otherwise><xsl:value-of select="normalize-space(.)"/></xsl:otherwise>
        </xsl:choose>
      </td>
    </tr>
  </xsl:template>

  <xsl:template match="podcast:person">
    <span class="person">
      <xsl:choose>
        <xsl:when test="@img">
          <img src="{@img}" alt="" loading="lazy"/>
        </xsl:when>
        <xsl:otherwise>
          <span class="noimg"><xsl:value-of select="substring(normalize-space(.), 1, 1)"/></span>
        </xsl:otherwise>
      </xsl:choose>
      <xsl:choose>
        <xsl:when test="@href">
          <a href="{@href}"><xsl:value-of select="."/></a>
        </xsl:when>
        <xsl:otherwise>
          <xsl:value-of select="."/>
        </xsl:otherwise>
      </xsl:choose>
      <span class="badge {@role}"><xsl:value-of select="@role"/></span>
    </span>
  </xsl:template>

</xsl:stylesheet>
