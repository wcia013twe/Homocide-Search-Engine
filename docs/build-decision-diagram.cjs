const fs = require('fs');
const esc = s => String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const W=1810,H=1020;
const ink='#2d3142', muted='#4f5d75', accent='#bf4520', link='#2e5aa8', paper='#f5f5f5';
const icons={search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
 branch:'<path d="M5 3v18m0-12h9a5 5 0 0 0 5-5m-14 9h9a5 5 0 0 1 5 5"/><circle cx="19" cy="3" r="2"/><circle cx="19" cy="20" r="2"/>',
 book:'<path d="M12 5C8 2 4 3 2 4v15c4-2 7-1 10 1 3-2 6-3 10-1V4c-3-1-7-2-10 1Zm0 0v15"/>',
 list:'<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M8 7h8M8 12h8M8 17h5"/>',
 code:'<path d="m8 5-6 7 6 7m8-14 6 7-6 7m-3-16-2 20"/>',
 flag:'<path d="M5 22V3c5-5 9 5 15 0v11c-6 5-10-5-15 0"/>',
 server:'<rect x="2" y="3" width="20" height="7" rx="2"/><rect x="2" y="14" width="20" height="7" rx="2"/><path d="M6 6h1m-1 11h1m5-11h6m-6 11h6"/>',
 db:'<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 4 18 4 18 0V5M3 12c0 4 18 4 18 0"/>',
 person:'<circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/>'};
let cells=[], shapes=[], wires=[];
function text(id,x,y,w,h,lines,size=15,color=ink,bold=false){
 const html=lines.map(esc).join('<br>');
 cells.push(`<mxCell id="${id}" value="${esc(html)}" style="text;html=1;align=left;verticalAlign=top;whiteSpace=wrap;overflow=hidden;fontFamily=Arial;fontSize=${size};fontColor=${color};${bold?'fontStyle=1;':''}" vertex="1" parent="1"><mxGeometry x="${x}" y="${y}" width="${w}" height="${h}" as="geometry"/></mxCell>`);
 shapes.push(`<text x="${x}" y="${y+size}" font-family="Arial,sans-serif" font-size="${size}" fill="${color}" ${bold?'font-weight="700"':''}>${lines.map((l,i)=>`<tspan x="${x}" dy="${i?size*1.45:0}">${esc(l)}</tspan>`).join('')}</text>`);
}
function box(id,x,y,w,h,title,lines,icon='code',focal=false){
 const color=focal?accent:muted, fill=focal?'#f8e9e3':'#ffffff';
 cells.push(`<mxCell id="${id}" value="" style="rounded=1;arcSize=6;whiteSpace=wrap;html=1;fillColor=${fill};strokeColor=${color};strokeWidth=${focal?2:1.3};" vertex="1" parent="1"><mxGeometry x="${x}" y="${y}" width="${w}" height="${h}" as="geometry"/></mxCell>`);
 shapes.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="7" fill="${fill}" stroke="${color}" stroke-width="${focal?2:1.3}"/>`);
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${icons[icon]}</svg>`;
 cells.push(`<mxCell id="${id}-icon" value="" style="shape=image;imageAspect=1;aspect=fixed;image=data:image/svg+xml,${encodeURIComponent(svg)};" vertex="1" parent="1"><mxGeometry x="${x+18}" y="${y+18}" width="27" height="27" as="geometry"/></mxCell>`);
 shapes.push(`<g transform="translate(${x+18},${y+18}) scale(1.125)" fill="none" stroke="${color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${icons[icon]}</g>`);
 text(id+'-title',x+57,y+19,w-70,30,[title],18,ink,true);
 text(id+'-body',x+18,y+61,w-34,h-65,lines,15,muted);
}
function edge(id,points,label,lx,ly,color=muted,dash=false){
 const pts=points.map(([x,y])=>`${x},${y}`).join(' ');
 cells.push(`<mxCell id="${id}" value="" style="endArrow=block;endFill=1;html=1;rounded=1;strokeColor=${color};strokeWidth=1.8;${dash?'dashed=1;dashPattern=5 4;':''}" edge="1" parent="1"><mxGeometry relative="1" as="geometry"><mxPoint x="${points[0][0]}" y="${points[0][1]}" as="sourcePoint"/><mxPoint x="${points.at(-1)[0]}" y="${points.at(-1)[1]}" as="targetPoint"/>${points.length>2?'<Array as="points">'+points.slice(1,-1).map(([x,y])=>`<mxPoint x="${x}" y="${y}"/>`).join('')+'</Array>':''}</mxGeometry></mxCell>`);
 wires.push(`<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linejoin="round" ${dash?'stroke-dasharray="5 4"':''} marker-end="url(#arrow-${color.slice(1)})"/>`);
 if(label){const width=label.length*7+16;
  cells.push(`<mxCell id="${id}-mask" value="${esc(label)}" style="text;html=1;align=center;verticalAlign=middle;fillColor=${paper};strokeColor=none;fontFamily=Arial;fontSize=13;fontColor=${color};" vertex="1" parent="1"><mxGeometry x="${lx}" y="${ly}" width="${width}" height="24" as="geometry"/></mxCell>`);
  shapes.push(`<rect x="${lx}" y="${ly}" width="${width}" height="24" fill="${paper}"/><text x="${lx+width/2}" y="${ly+16}" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" fill="${color}">${esc(label)}</text>`);
 }
}
text('title',65,35,1670,50,['Incident research: two decisions, one controlled loop'],32,ink,true);
text('subtitle',65,90,1680,50,['LangChain handles model/tool calls. LangGraph carries state and follows routes defined in code.'],18,muted);
text('legend',65,143,1680,35,['ORANGE  decision judgments     •     WHITE  tools / code     •     BLUE DASHED  Decision API calls'],14,muted);
box('seed',80,205,260,100,'Seed record',['Name + affiliation / city / date'], 'person');
box('search',80,365,260,155,'1  Get search leads',['Exa or Brave adapter','Save query + returned results','Replay: use saved SQLite rows'], 'search');
box('worth',420,365,260,155,'2  Worth reading?',['Input: identifiers + gaps','Title + URL + short excerpt','Output: read / reject + scores'], 'branch',true);
box('read',760,365,260,155,'3  Read source',['Fetch only selected URLs','Replay: saved excerpts only','Keep source text + provenance'], 'book');
box('extract',1100,365,260,155,'4  Extract claims',['LLM: candidate field values','Supporting passages + URLs','Keep conflicting claims'], 'list');
box('resolve',1100,615,260,155,'5  Supported value?',['Input: claims + supporting text','Output: fill / leave empty + scores','Primary source is helpful, optional'], 'branch',true);
box('gaps',760,615,260,155,'6  Fill + find gaps',['Fill supported values immediately','Keep URL + passage + scores','Gaps = missing or conflicting'], 'code');
box('control',420,615,260,155,'7  Choose next step',['Code: unread useful source first','Else query for remaining gap','Track attempts for each gap'], 'code');
box('finish',80,615,260,155,'8  Finish this pass',['Required fields filled OR','attempt / no-progress limit hit','Keep unresolved fields explicit'], 'flag');
box('api',1460,365,280,345,'Databricks ai_decide',['One API, two judgment tasks','','A  Source value: read / reject','B  Data: fill / leave empty','','Responses: choices + scores','No pending-verification status','','Catalog: system.ai.ai_decide','Present; execution probes failed'], 'server');
text('reject-note',430,545,300,45,['reject = skip this pass','Retain result for reconsideration'],13,muted);
box('audit',80,880,1280,100,'Audit trail / SQLite + saved artifacts',['Record every stage: inputs, source IDs, rubric version, decisions, scores, actions and per-gap search attempts.'], 'db');
text('status',1460,800,290,140,['PROPOSED DESIGN','Replay test: saved Padmini results.','No new searches or deployment.','Supported values fill immediately.','Keep all conflicting source claims.'],14,muted);
edge('seed-search',[[210,305],[210,365]],'seed',224,322);
edge('search-worth',[[340,435],[420,435]],'',0,0);
edge('worth-read',[[680,435],[760,435]],'read',685,404);
edge('read-extract',[[1020,435],[1100,435]],'',0,0);
edge('extract-resolve',[[1230,520],[1230,615]],'claims',1240,557);
edge('resolve-gaps',[[1100,690],[1020,690]],'',0,0);
text('resolution-label',1026,657,70,25,['update'],12,muted);
edge('gaps-control',[[760,690],[680,690]],'',0,0);
edge('control-stop',[[420,690],[340,690]],'stop',344,654);
edge('reject',[[550,520],[550,542]],'',0,0,muted,true);
edge('unread',[[550,615],[550,590],[890,590],[890,520]],'useful source still unread',637,576);
edge('new-search',[[500,770],[500,825],[35,825],[35,435],[80,435]],'gap + budget: generate query, deduplicate, search_attempts += 1',90,792);
edge('api-a',[[550,365],[550,255],[1600,255],[1600,365]],'A: classify leads / return choices',790,243,link,true);
edge('api-b',[[1360,690],[1410,690],[1410,580],[1460,580]],'B',1378,647,link,true);
text('audit-note',80,990,1550,25,['Audit applies to every stage. API failure pauses the pass and records an error; it never becomes a read/reject or fill decision.'],13,muted);
const xml=`<?xml version="1.0" encoding="UTF-8"?><mxfile host="app.diagrams.net" version="26.0.0"><diagram id="incident-loop" name="Decision loop"><mxGraphModel dx="1810" dy="1020" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1810" pageHeight="1020" background="${paper}" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>${cells.join('')}</root></mxGraphModel></diagram></mxfile>`;
fs.writeFileSync('docs/incident-langchain-decision-loop.drawio',xml);
const markers=[muted,link].map(c=>`<marker id="arrow-${c.slice(1)}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10Z" fill="${c}"/></marker>`).join('');
fs.writeFileSync('docs/incident-langchain-decision-loop.svg',`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs>${markers}</defs><rect width="100%" height="100%" fill="${paper}"/>${wires.join('')}${shapes.join('')}</svg>`);
console.log('Created editable draw.io diagram and matching SVG preview.');




