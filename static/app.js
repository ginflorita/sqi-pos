'use strict';
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const e = escapeHTML;
const paths = {
 expand:'M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5', collapse:'M3 8h5V3M21 8h-5V3M16 21v-5h5M8 21v-5H3',
 cart:'M3 3h2l2 12h12l2-8H6M9 20h.01M18 20h.01', grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
 box:'m3 7 9-4 9 4v10l-9 4-9-4zm0 0 9 4 9-4M12 11v10M7 5l10 4', receipt:'M5 3h14v18l-3-2-4 2-4-2-3 2zm4 5h6M9 12h6M9 16h3',
 chart:'M4 20V4M4 20h17M9 16v-4M14 16V8M19 16V5', users:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M16 3a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.9M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0',
 shield:'m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zm-4 9 3 3 5-6', settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M9 3h6l1 3 3 1 2 5-2 3-1 4-4 2-4-1-3-3-3-2-1-5 3-3z',
 search:'m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0', arrow:'M4 12h16m-6-6 6 6-6 6', plus:'M12 5v14M5 12h14', close:'m6 6 12 12M6 18 18 6',
 logout:'M9 4H4v16h5M9 12h12m-4-4 4 4-4 4', clock:'M12 8v4l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0', check:'m5 12 4 4L19 6',
 down:'m7 10 5 5 5-5', download:'M12 3v12m-5-5 5 5 5-5M5 17v4h14v-4', print:'M6 9V3h12v6M6 17H3V9h18v8h-3M6 14h12v7H6z',
 leaf:'M20 3c-9-2-17 2-16 9 1 6 8 7 12 3 4-4 4-12 4-12M4 21l11-11', cup:'M5 8h12v9c0 5-12 5-12 0zm12 1h3c3 0 3 6 0 6h-3M8 2v3M13 2v3',
 bag:'M5 7h14l2 14H3zm3 0V6a4 4 0 0 1 8 0v1', sun:'M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1 1M18 18l1 1M5 19l1-1M18 6l1-1M17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0',
 edit:'m15 4 5 5M4 16 16 4a3 3 0 0 1 4 4L8 20H4z', image:'M3 3h18v18H3zm0 14 6-6 4 4 3-3 5 5M8 7h.01', refresh:'M20 7v5h-5M4 17v-5h5M5 7a8 8 0 0 1 14-2l1 2M4 17l1 2a8 8 0 0 0 14-2',
 laptop:'M4 3h16v13H4zM2 20l2-4h16l2 4z', dots:'M5 12h.01M12 12h.01M19 12h.01'
};
const icon = name => `<svg class="icon" aria-hidden="true" viewBox="0 0 24 24"><path d="${paths[name] || paths.box}"/></svg>`;
const money = n => new Intl.NumberFormat('en', {style:'currency', currency:S.bazaar?.currency_code || 'PHP'}).format((n||0)/100);
const receiptNumber = value => String(value ?? '').replace(/^BZ-(\d{3,}-\d{6,})$/, 'SQI-$1');
const num = n => new Intl.NumberFormat('en').format(n||0);
const percentLabel = bp => `${(bp/100).toFixed(2).replace(/\.00$/,'').replace(/(\.\d)0$/,'$1')}%`;
const timestamp = s => s ? new Date(s).toLocaleString('en', {timeZone:S.bazaar?.timezone || 'Asia/Manila', month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—';
const minor = value => {
  const s=String(value).trim();
  if(!/^\d{1,10}(\.\d{1,2})?$/.test(s)) throw new Error('Enter a positive amount with up to two decimal places.');
  const [a,b='']=s.split('.'); return Number(a)*100+Number(b.padEnd(2,'0'));
};
const key = () => [...crypto.getRandomValues(new Uint8Array(24))].map(n=>n.toString(16).padStart(2,'0')).join('');
const S={csrf:'',user:null,terminal:null,bazaar:null,day:null,shift:null,page:location.hash.slice(1)||'reports',products:[],productDrafts:[],categories:[],ticket:null,cart:[],search:'',category:'all',productPage:0,filters:{},online:true,paying:false,cartError:false,receiptPrinter:null};
const managerAccess=()=>['manager','it_admin'].includes(S.user?.role);
const roleLabel=user=>({it_admin:'IT System Administrator',manager:'Manager',cashier:'Cashier'})[user?.role]||'Unknown';
let cartQueue=Promise.resolve(), currentReceipt=null, pollBusy=false, catalogPollBusy=false, creatingTicket=null, cartPending=0, quantityDialogOpening=false, checkoutFullscreen=false, browserFullscreenOwned=false, paymentConfirmationCancel=null, shiftConfirmationCancel=null, pendingProductImport=null, managementOpen=false, backupPage=0, shiftHistoryPage=1, transactionPage=1, transactionSearch='', catalogSearch='', catalogDraftPage=1, catalogProductPage=1, reportEventId=null, auditEventId=null, inventoryEventId=null, archiveEventName='', bootRetryTimer=null;
const inventoryFilters={q:'',category_id:'',from:'',to:'',view:'products',product_page:1,movement_page:1};
let inventoryRenderId=0;
async function api(path, method='GET', data, isForm=false){
  let response;
  try { response=await fetch('/api'+path,{method,credentials:'same-origin',headers:{...(method!=='GET'?{'X-CSRF-Token':S.csrf}:{}),...(!isForm&&data?{'Content-Type':'application/json'}:{})},body:data?(isForm?data:JSON.stringify(data)):undefined}); }
  catch{S.online=false;updateConnection();throw new Error('Connection lost. Reconnect and check the current ticket before retrying payment.');}
  S.online=true;updateConnection();
  let result;try{result=await response.json();}catch{result={error:response.status===404
    ? 'This feature is not available in the running server. Restart SQI POS and try again.'
    : 'The server returned an unexpected response. Refresh the page and try again.'};}
  if(!response.ok){if(response.status===401&&S.user){S.user=null;renderAuth(false);}const error=new Error(result.error||'The request could not be completed.');error.status=response.status;if(response.status===404&&(!response.headers.get('content-type')?.includes('application/json')||path==='/server-info'))error.code='update';throw error;}
  return result;
}
function toast(message,error=false){const t=$('#toast');t.textContent=message;t.className='show'+(error?' error':'');clearTimeout(toast.timer);toast.timer=setTimeout(()=>t.className='',6000);}
function updateConnection(){const node=$('#connection-state');if(node)node.innerHTML=`<span class="dot"></span>${S.online?'Local server connected':'Connection lost'}`;const banner=$('#connection-banner');if(banner){banner.hidden=S.online;banner.textContent='Connection lost. Checkout is paused. Reconnect to check your ticket.';}}
function button(label,action,style='light',i='',extra=''){return `<button type="button" class="btn ${style}" data-action="${action}" ${extra}>${i?icon(i):''}${label}</button>`;}
function field(label,name,type='text',value='',opts=''){return `<div class="field"><label for="f-${name}">${label}</label><input id="f-${name}" name="${name}" type="${type}" value="${e(value)}" ${opts}></div>`;}
function approval(){return `<div class="field full"><label for="f-manager_password">Confirm with your manager password</label><input id="f-manager_password" name="manager_password" type="password" autocomplete="current-password" required minlength="12"></div>`;}
function selectField(label,name,options,selected='',extra=''){return `<div class="field"><label for="f-${name}">${label}</label><select id="f-${name}" name="${name}" ${extra}>${options.map(([v,l])=>`<option value="${e(v)}" ${String(v)===String(selected)?'selected':''}>${e(l)}</option>`).join('')}</select></div>`;}
function empty(title,description,action='',label=''){return `<div class="empty">${icon('box')}<h3>${e(title)}</h3><p>${e(description)}</p>${action?button(label,action,'green','plus'):''}</div>`;}
function table(headers,rows){return `<div class="table-scroll"><table><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;}
function pill(text,style='success'){return `<span class="pill ${style}"><span class="dot"></span>${e(text)}</span>`;}
function heading(title,description,actions=''){return `<div class="page-heading"><div><div class="eyebrow">SQI GROUP INT'L CORP · PHILIPPINES</div><h1>${e(title)}</h1><p>${e(description)}</p></div><div class="actions">${actions}</div></div>`;}
function modal(title,body,wide=false){if(paymentConfirmationCancel)paymentConfirmationCancel();if(shiftConfirmationCancel)shiftConfirmationCancel();$('#modal-root').innerHTML=`<div class="modal-overlay"><section class="modal ${wide?'wide':''}" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-head"><h2 id="modal-title">${e(title)}</h2><button class="icon-btn" aria-label="Close dialog" data-action="close-modal">${icon('close')}</button></div><div class="modal-body">${body}</div></section></div>`;setTimeout(()=>($('input:not([type=hidden]),select', $('.modal-body'))||$('.modal-head button'))?.focus({preventScroll:true}),30);}
function closeModal(){if(S.paying)return;if(paymentConfirmationCancel){paymentConfirmationCancel();return;}if(shiftConfirmationCancel){shiftConfirmationCancel();return;}const wasQuantity=['Choose quantity','Set quantity'].includes($('#modal-title')?.textContent);$('#modal-root').innerHTML='';currentReceipt=null;pendingProductImport=null;if(wasQuantity&&S.page==='checkout'){const search=$('#product-search');search?.focus({preventScroll:true});search?.select();}}
function confirmLogout(){
  if(!S.user||S.paying||$('.modal'))return;
  modal('Sign out?',`<p>Sign out of ${e(S.user.display_name)}?</p>${S.shift?'<p class="muted signout-note">Your cashier shift and any unpaid order will stay open. Close them first if you are done selling.</p>':''}<div class="modal-actions">${button('Stay signed in','close-modal','light')}${button('Sign out','confirm-logout','green','logout')}</div>`);
}
async function signOut(){
  await cartQueue;
  await api('/logout','POST',{});
  S.ticket=null;S.cart=[];S.page='reports';
  history.replaceState(null,'',`${location.pathname}${location.search}`);
  await boot();
}
function formModal(title,body,onSubmit,submit='Save',wide=false){modal(title,`<form id="modal-form" class="form-grid">${body}<div class="form-error" role="alert"></div><div class="modal-actions">${button('Cancel','close-modal','light')}<button type="submit" class="btn green">${submit}${icon('arrow')}</button></div></form>`,wide);$('#modal-form').addEventListener('submit',async ev=>{ev.preventDefault();const form=ev.currentTarget;const submitButton=$('[type=submit]',form);if(submitButton.disabled)return;submitButton.disabled=true;$('.form-error',form).textContent='';try{await onSubmit(Object.fromEntries(new FormData(form)),form);}catch(error){$('.form-error',form).textContent=error.message;}finally{submitButton.disabled=false;}});}
async function refreshState(){const data=await api('/state');Object.assign(S,data);return data;}
async function loadCatalog(){const data=await api('/catalog');S.products=data.products;S.productDrafts=data.drafts||[];S.categories=data.categories;}
async function refreshCheckoutStock(){
  if(catalogPollBusy||!S.user||S.page!=='checkout'||document.hidden||S.paying||cartPending)return;
  catalogPollBusy=true;
  try{
    const userId=S.user.user_id;
    const data=await api('/catalog?background=1');
    if(S.user?.user_id!==userId||S.page!=='checkout'||!$('#product-grid')||cartPending)return;
    const changed=JSON.stringify([S.products,S.categories])!==JSON.stringify([data.products,data.categories]);
    S.products=data.products;S.productDrafts=data.drafts||[];S.categories=data.categories;
    if(!changed)return;
    const productScroll=$('#product-grid').scrollTop;
    renderCategorySelect();renderProducts();renderCart();
    $('#product-grid').scrollTop=productScroll;
  }catch{}finally{catalogPollBusy=false;}
}
function renderAuth(setup){
  if(paymentConfirmationCancel)paymentConfirmationCancel();
  void exitCheckoutFullscreen();
  $('#modal-root').innerHTML='';
  $('#app').innerHTML=`<div class="auth auth-login"><header class="auth-login-brand"><img src="/static/sqi-logo.png" alt="SQI logo"><strong>SQI Group Int'l Corp Philippines</strong></header><main class="auth-form"><div class="eyebrow">${setup?'LET’S SET UP YOUR COUNTER':'WELCOME BACK'}</div><h2>${setup?'Set up your SQI counter.':'Your counter is waiting.'}</h2><p>${setup?'Create the manager account on this host laptop. You can add your second cashier after setup.':'Sign in with your own account to open your shift.'}</p><form id="auth-form" class="form-grid">${setup?field('Your name','display_name','text','','required autocomplete="name"')+field('Business name','bazaar_name','text',"SQI Group Int'l Corp - Philippines",'required maxlength="120"'):''}${field('Username','username','text','','required autocomplete="username" minlength="3" maxlength="50"')}${field('Password','password','password','','required autocomplete="'+(setup?'new-password':'current-password')+'" '+(setup?'minlength="12"':''))}${setup?selectField('Currency','currency_code',[['PHP','PHP · Philippine peso'],['USD','USD · US dollar'],['TWD','TWD · Taiwan dollar'],['SGD','SGD · Singapore dollar'],['EUR','EUR · Euro'],['GBP','GBP · British pound'],['MYR','MYR · Malaysian ringgit'],['THB','THB · Thai baht'],['HKD','HKD · Hong Kong dollar'],['AUD','AUD · Australian dollar']],'PHP')+field('Business timezone','timezone','text','Asia/Manila','required'):''}<div class="form-error" role="alert"></div><div class="field full"><button class="btn green" type="submit">${setup?'Create my counter':'Sign in'}${icon('arrow')}</button></div></form>${setup?'<div class="auth-note">Use at least 12 characters for your password. Currency and timezone apply to this counter.</div>':''}</main><footer class="auth-footer">www.sqigroup.ph | 2027</footer></div>`;
  $('#auth-form').addEventListener('submit',async ev=>{ev.preventDefault();const form=ev.currentTarget;const b=$('[type=submit]',form);b.disabled=true;$('.form-error',form).textContent='';try{await api(setup?'/setup':'/login','POST',Object.fromEntries(new FormData(form)));await boot();}catch(error){$('.form-error',form).textContent=error.message;}finally{b.disabled=false;}});
}
const nav=[['checkout','cart','Checkout'],['catalog','grid','Products'],['inventory','box','Inventory'],['transactions','receipt','Transactions'],['reports','chart','Reports'],['shifts','clock','Cashier shifts'],['team','users','Team'],['audit','shield','Audit trail'],['management','settings','Business day'],['events','sun','Events'],['discounts','chart','Discounts'],['backups','download','Backups'],['printer','print','Printer']];
const managementPages=new Set(['management','events','discounts','backups','printer']);
function shell(){
  const allowed=nav.filter(([id])=>!managementPages.has(id)&&(managerAccess()||['checkout','transactions','shifts'].includes(id)));
  const initials=S.user.display_name.split(' ').slice(0,2).map(w=>w[0]).join('').toUpperCase();
  managementOpen=managementPages.has(S.page);
  const managementNav=managerAccess()?`<div class="nav-management"><button id="management-toggle" type="button" class="${managementOpen?'group-active':''}" data-action="toggle-management" aria-expanded="${managementOpen}" aria-controls="management-subnav" title="Management">${icon('settings')}<span>Management</span>${icon('down')}</button><div class="nav-submenu" id="management-subnav" ${managementOpen?'':'hidden'}>${nav.filter(([id])=>managementPages.has(id)&&(id!=='events'||S.user.role==='it_admin')).map(([id,i,label])=>`<button data-page="${id}" class="${S.page===id?'active':''}" title="${label}">${icon(i)}<span>${label}</span></button>`).join('')}</div></div>`:'';
  $('#app').innerHTML=`<div class="shell"><aside class="sidebar"><div class="brand company-brand"><img src="/static/sqi-logo.png" alt="SQI company logo" width="5442" height="3064"><span class="company-brand-name">SQI Group Int'l Corp<small>Philippines</small></span></div><div class="nav-label">WORKSPACE</div><nav class="nav">${allowed.map(([id,i,label],index)=>`${index===5?'<div class="nav-gap"></div>':''}<button data-page="${id}" class="${S.page===id?'active':''}" title="${label}">${icon(i)}<span>${label}</span></button>`).join('')}${managementNav}</nav><div class="side-foot"><div class="local-status" id="connection-state"><span class="dot"></span>Local server connected</div><div class="side-user"><div class="avatar">${e(initials)}</div><div><strong>${e(S.user.display_name)}</strong><small>${e(roleLabel(S.user))}</small></div><button class="icon-btn" title="Sign out" aria-label="Sign out" data-action="logout">${icon('logout')}</button></div></div></aside><main class="main"><header class="topbar"><div class="breadcrumb">SQI Group <span>/</span><b id="page-name">Checkout</b></div><div class="top-right"><span class="date-label">${new Intl.DateTimeFormat('en',{timeZone:S.bazaar?.timezone||'Asia/Manila',month:'short',day:'numeric',year:'numeric'}).format(new Date())}</span>${pill(S.bazaar?(S.day?'Day '+S.day.day_number+' is open':'Day closed'):'No event open',S.day?'success':'warn')}<div class="avatar">${e(initials)}</div></div></header><div id="connection-banner" class="connection-banner" hidden></div><div id="page" class="page"></div></main></div>`;
}
function renderBootError(error){
  clearTimeout(bootRetryTimer);
  if(error.code==='update'){
    const local=['localhost','127.0.0.1'].includes(location.hostname);
    $('#app').innerHTML=`<main class="boot-error" role="alert"><h1>SQI POS is updating</h1><p>The app files are newer than the server currently running on the main laptop.</p><p>${local?'On this laptop, double-click <strong>Start SQI POS</strong>.':'Ask the person at the main laptop to double-click <strong>Start SQI POS</strong>.'} This screen will reconnect by itself.</p><button type="button" class="btn green" id="retry-boot">Check again</button></main>`;
    $('#retry-boot').addEventListener('click',()=>location.reload());
    const checkAgain=async()=>{
      try{const response=await fetch('/api/server-info',{cache:'no-store'});if(response.ok){const info=await response.json();if(!info.restart_needed){location.reload();return;}}}catch{}
      bootRetryTimer=setTimeout(checkAgain,4000);
    };
    bootRetryTimer=setTimeout(checkAgain,4000);
    return;
  }
  const detail=error.status===503
    ? 'The database is busy. If DB Browser for SQLite is open, resolve its pending changes and close the database, then retry.'
    : 'Check that the local server is running, then retry.';
  $('#app').innerHTML=`<main class="boot-error" role="alert"><h1>Unable to open your counter</h1><p>${e(error.message)}</p><p>${detail}</p><button type="button" class="btn green" id="retry-boot">Try again</button></main>`;
  $('#retry-boot').addEventListener('click',boot,{once:true});
}
async function boot(){try{clearTimeout(bootRetryTimer);await cartQueue;const server=await api('/server-info');if(server.restart_needed){const error=new Error('The POS server needs to restart to finish this update.');error.code='update';throw error;}await refreshState();if(!S.user)return renderAuth(S.setup_required);if(!nav.some(([id])=>id===S.page))S.page='reports';if(!managerAccess()&&!['checkout','transactions','shifts'].includes(S.page))S.page='checkout';if(S.page==='events'&&S.user.role!=='it_admin')S.page='reports';await loadCatalog();shell();await navigate(S.page);}catch(error){renderBootError(error);}}
async function navigate(page){
  if(page==='settings')page='management';
  if(page==='inventory'&&!S.bazaar&&!inventoryEventId){await navigate(S.user.role==='it_admin'?'events':'management');toast('Start an event to track its inventory.',true);return;}
  if(page==='checkout'&&(!S.day||!S.shift)){
    await navigate(managerAccess()?'reports':'transactions');
    return checkoutStartPrompt();
  }
  if(page!=='checkout')await exitCheckoutFullscreen();
  if(page==='backups'&&S.page!=='backups')backupPage=0;
  S.page=page;if(location.hash.slice(1)!==page)history.replaceState(null,'',`${location.pathname}${location.search}#${page}`);$$('[data-page]').forEach(b=>b.classList.toggle('active',b.dataset.page===page));$('#page-name').textContent=nav.find(n=>n[0]===page)?.[2]||page;
  if(managementPages.has(page))managementOpen=true;
  const submenu=$('#management-subnav'),toggle=$('#management-toggle');
  if(submenu)submenu.hidden=!managementOpen;
  if(toggle){toggle.setAttribute('aria-expanded',String(managementOpen));toggle.classList.toggle('group-active',managementPages.has(page));}
  const renderers={checkout:renderCheckout,catalog:renderCatalog,inventory:renderInventory,transactions:renderTransactions,reports:renderReports,shifts:renderShifts,team:renderTeam,audit:renderAudit,management:renderManagement,events:renderEvents,discounts:renderDiscounts,backups:renderBackups,printer:renderPrinter};
  try{await renderers[page]();}catch(error){if(error.code==='update'){renderBootError(error);return;}toast(error.message,true);$('#page').innerHTML=empty('Unable to open this page',error.message);}
}
function toggleManagement(){
  managementOpen=!managementOpen;
  const submenu=$('#management-subnav'),toggle=$('#management-toggle');
  if(submenu)submenu.hidden=!managementOpen;
  if(toggle)toggle.setAttribute('aria-expanded',String(managementOpen));
}
function syncCheckoutFullscreen(){
  document.body.classList.toggle('checkout-fullscreen',checkoutFullscreen);
  const control=$('[data-action=toggle-checkout-fullscreen]');
  if(control){control.innerHTML=icon(checkoutFullscreen?'collapse':'expand')+(checkoutFullscreen?'Exit fullscreen':'Fullscreen');control.setAttribute('aria-pressed',String(checkoutFullscreen));control.title=checkoutFullscreen?`Exit fullscreen and open ${managerAccess()?'Reports':'Transactions'} (Esc)`:'Open checkout fullscreen';}
}
async function enterCheckoutFullscreen(){
  checkoutFullscreen=true;syncCheckoutFullscreen();
  if(!document.fullscreenElement&&document.documentElement.requestFullscreen){
    browserFullscreenOwned=true;
    try{await document.documentElement.requestFullscreen();}catch{browserFullscreenOwned=false;}
  }
}
async function exitCheckoutFullscreen(){
  checkoutFullscreen=false;syncCheckoutFullscreen();
  if(browserFullscreenOwned){browserFullscreenOwned=false;if(document.fullscreenElement)try{await document.exitFullscreen();}catch{}}
}
async function leaveCheckoutFullscreen(){
  if(!checkoutFullscreen&&!browserFullscreenOwned)return;
  await exitCheckoutFullscreen();
  if(S.page==='checkout'&&S.user)await navigate(managerAccess()?'reports':'transactions');
}
function checkoutModePrompt(){
  if($('.modal')||S.paying)return;
  modal('Open checkout',`<p>Checkout will open in fullscreen. Press <strong>Esc</strong> to exit and return to ${managerAccess()?'Reports':'Transactions'}.</p><p>Click OK to proceed.</p><div class="modal-actions">${button('Cancel','close-modal','light')}${button('OK','checkout-fullscreen','green','expand')}</div>`);
}
function checkoutStartPrompt(){
  if($('.modal')||S.paying)return;
  if(!S.bazaar){
    modal('No event is open',`<p>${S.user.role==='it_admin'?'Start the next event in Events, then a manager can open its first business day.':'Ask the IT System Administrator to start the next event. A manager can then open the business day.'}</p><div class="modal-actions">${button('OK','close-modal','green')}${S.user.role==='it_admin'?button('Go to Events','go-to-events','light','sun'):''}</div>`);
    return;
  }
  if(!S.day){
    if(managerAccess())return openDay(true);
    modal('Checkout is closed',`<p>The business day has not been started. Ask the system manager to start the day before you open your shift or make a sale.</p><div class="modal-actions">${button('OK','close-modal','green')}</div>`);
    return;
  }
  if(!S.shift)return openShift(true);
  checkoutModePrompt();
}
async function requestCheckout(){
  if($('.modal')||S.paying)return;
  await refreshState();
  if(!S.user)return renderAuth(false);
  if((!S.day||!S.shift)&&S.page==='checkout')return navigate('checkout');
  checkoutStartPrompt();
}
async function openCheckoutFullscreen(){
  await refreshState();
  if(!S.user)return renderAuth(false);
  closeModal();
  if(!S.day||!S.shift)return navigate('checkout');
  await enterCheckoutFullscreen();
  await cartQueue;await navigate('checkout');
}
document.addEventListener('fullscreenchange',()=>{if(browserFullscreenOwned&&!document.fullscreenElement)void leaveCheckoutFullscreen();});
async function renderCheckout(){
  if(!S.day||!S.shift)return navigate('checkout');
  const [,printing]=await Promise.all([loadCatalog(),api('/receipt-printer')]);
  S.receiptPrinter=printing.printer;
  let recoveredSale=null,pendingOpen=false;
  for(const storageKey of Object.keys(localStorage).filter(k=>k.startsWith(`bazaar-pending-${S.user.user_id}-`))){
    let body;try{body=JSON.parse(localStorage.getItem(storageKey));}catch{continue;}
    if(!Number.isInteger(body?.purchase_ticket_id))continue;
    const status=await api('/tickets/'+body.purchase_ticket_id);
    if(status.sale_id){recoveredSale=status.sale_id;localStorage.removeItem(storageKey);}
    else if(status.state==='open')pendingOpen=true;
    else localStorage.removeItem(storageKey);
  }
  const tickets=await api('/tickets');
  if(tickets.tickets.length){S.ticket=await api('/tickets/'+tickets.tickets[0].purchase_ticket_id);S.cart=S.ticket.lines.map(l=>({product_id:l.product_id,quantity:l.quantity}));}
  else{S.ticket=null;S.cart=[];}
  S.cartError=false;
  $('#page').innerHTML=`<div class="checkout-heading"><h1>The counter</h1><p>Good things, one sale at a time.</p><div class="actions">${printerConnectButton(S.receiptPrinter)}${S.shift?button('Close my shift','close-shift','light','clock'):''}${managerAccess()?button(S.day?'Finish day':'Start day','day-steps','light','sun'):''}${button(checkoutFullscreen?'Exit fullscreen':'Fullscreen','toggle-checkout-fullscreen','light',checkoutFullscreen?'collapse':'expand',`aria-pressed="${checkoutFullscreen}"`)}</div></div><div class="checkout-layout"><section class="shop-panel"><div class="search-row"><div class="search">${icon('search')}<input id="product-search" placeholder="Search by name, SKU, or barcode" aria-label="Search by product name, SKU, or barcode" value="${e(S.search)}" autocomplete="off" autocapitalize="off" spellcheck="false"><kbd>/</kbd></div><select id="checkout-category" class="checkout-category-select" aria-label="Filter products by category"></select></div><p class="search-hint">Scan a barcode or SKU to add one item. Scan again to add another, or use Qty in the order to set a larger total. Choose a category to browse.</p><div class="section-line"><strong>Browse products</strong><span id="product-count"></span></div><div class="product-list" id="product-grid"></div><nav class="product-pager" id="product-pager" aria-label="Browse product pages"></nav><p class="stock-note">${icon('shield')}Stock is checked again when you complete the sale.</p></section><aside class="cart" id="cart"></aside></div>`;
  const searchInput=$('#product-search');
  let scanTimer;
  const exactMatches=query=>S.products.filter(p=>p.active&&(p.barcode===query||p.sku.toLowerCase()===query.toLowerCase()));
  async function addScannedProduct(query,showUnmatched){
    if(!searchInput.isConnected||S.page!=='checkout'||searchInput.value.trim()!==query||quantityDialogOpening||$('.modal'))return;
    if(S.paying){if(showUnmatched)toast('Finish the current payment before scanning another.',true);return;}
    const matches=exactMatches(query);
    if(matches.length!==1){if(showUnmatched){toast(matches.length?'More than one item matches. Choose one from the list.':'No active product matches that barcode or SKU. Try searching by name.',true);searchInput.select();}return;}
    const product=matches[0];
    searchInput.value='';S.search='';S.productPage=0;renderProducts();searchInput.focus({preventScroll:true});
    try{
      await addProduct(product.product_id,1);
      if(!S.cartError)toast('Added 1 × '+product.description+'. Scan again for another or use Qty to set the total.');
    }catch(error){toast(error.message,true);searchInput.focus({preventScroll:true});}
  }
  searchInput.addEventListener('input',ev=>{
    clearTimeout(scanTimer);
    S.search=ev.target.value;S.productPage=0;renderProducts();
    const query=searchInput.value.trim();
    if(query&&exactMatches(query).length===1){
      scanTimer=setTimeout(()=>{if(searchInput.value.trim()===query)void addScannedProduct(query,false);},250);
    }
  });
  searchInput.addEventListener('keydown',async ev=>{
    if(ev.key!=='Enter')return;
    ev.preventDefault();clearTimeout(scanTimer);
    const query=searchInput.value.trim();
    if(query)await addScannedProduct(query,true);
  });
  renderCategorySelect();renderProducts();renderCart();
  if(recoveredSale){await showReceipt(recoveredSale);toast('Recovered the saved payment. This is the original receipt.');}
  else if(pendingOpen)await paymentModal();
  else{searchInput.focus({preventScroll:true});searchInput.select();}
}
function canStartPrintHelper(){return ['localhost','127.0.0.1','::1','[::1]'].includes(location.hostname);}
function printerConnectButton(printer){return printer?.enabled&&!printer.online&&canStartPrintHelper()?button('Connect printer','start-print-helper','green','print'):'';}
async function startPrintHelper(){
  const buttons=$$('[data-action=start-print-helper]');
  buttons.forEach(b=>{b.disabled=true;b.innerHTML=icon('refresh')+'Starting printer…';});
  try{
    await api('/receipt-printer/start-helper','POST',{});
    for(let attempt=0;attempt<15;attempt++){
      await new Promise(resolve=>setTimeout(resolve,1000));
      const data=await api('/receipt-printer');
      S.receiptPrinter=data.printer;
      if(data.printer?.online){
        buttons.forEach(b=>b.remove());
        if(S.page==='printer')await renderPrinter();
        toast(data.printer.enabled?'Receipt printer connected. It will print automatically after payment.':'Print helper connected. Choose a printer and turn on automatic printing in Settings.');
        return;
      }
    }
    throw new Error('The printer helper started but did not connect. Ask a manager to check the printer and helper.log.');
  }catch(error){
    buttons.forEach(b=>{if(b.isConnected){b.disabled=false;b.innerHTML=icon('print')+'Connect printer';}});
    throw error;
  }
}
function renderCategorySelect(){
  const select=$('#checkout-category');if(!select)return;
  const categories=S.categories.filter(c=>c.active);
  if(S.category!=='all'&&!categories.some(c=>String(c.category_id)===String(S.category))){S.category='all';S.productPage=0;}
  select.innerHTML=`<option value="all">All categories (${num(S.products.filter(p=>p.active).length)})</option>`+categories.map(c=>`<option value="${c.category_id}">${e(c.name)} (${num(S.products.filter(p=>p.active&&p.category_id===c.category_id).length)})</option>`).join('');
  select.value=String(S.category);
}
function productVisual(p){return p.product_image_id?`<img src="/api/images/${p.product_image_id}" alt="${e(p.description)}" loading="lazy">`:icon(['bag','cup','leaf','box'][p.category_id%4]);}
function viewProductImage(pid){
  const product=S.products.find(p=>p.product_id===pid);
  if(!product?.product_image_id)return;
  modal('Product photo',`<figure class="product-photo-viewer"><img src="/api/images/${product.product_image_id}" alt="${e(product.description)}"><figcaption><strong>${e(product.sku)}</strong><span>${e(product.description)}</span></figcaption></figure><div class="modal-actions">${button('Close','close-modal','light')}</div>`,true);
}
const PRODUCT_PAGE_SIZE=24;
function renderProducts(){
  const search=S.search.trim().toLowerCase();
  const products=S.products.filter(p=>p.active&&(S.category==='all'||String(p.category_id)===String(S.category))&&[p.sku,p.description,p.short_description||'',p.barcode||''].some(v=>v.toLowerCase().includes(search)));
  const pageCount=Math.max(1,Math.ceil(products.length/PRODUCT_PAGE_SIZE));
  S.productPage=Math.max(0,Math.min(S.productPage,pageCount-1));
  const first=S.productPage*PRODUCT_PAGE_SIZE;
  const pageProducts=products.slice(first,first+PRODUCT_PAGE_SIZE);
  $('#product-count').textContent=products.length?`Showing ${first+1}–${Math.min(first+PRODUCT_PAGE_SIZE,products.length)} of ${num(products.length)} products`:'0 products';
  const rows=pageProducts.map(p=>`<tr class="${p.quantity_on_hand?'':'checkout-product-unavailable'}"><td class="checkout-product-code">${e(p.sku)}</td><td class="checkout-product-code">${e(p.barcode||'—')}</td><td class="checkout-product-description">${e(p.description)}${p.product_image_id?` <button type="button" class="checkout-product-photo" data-action="view-product-image" data-id="${p.product_id}" aria-label="View photo of ${e(p.description)}">${icon('image')} Photo</button>`:''}</td><td class="checkout-product-stock ${p.quantity_on_hand<6?'low':''}">${p.quantity_on_hand?`${num(p.quantity_on_hand)} <small>${e(p.unit)}</small>`:'Out of stock'}</td><td class="checkout-product-price">${money(p.amount_minor)}</td><td class="checkout-product-add"><button type="button" data-add="${p.product_id}" aria-label="Choose quantity for ${e(p.description)}" ${p.quantity_on_hand?'':'disabled'}>${icon('plus')}</button></td></tr>`);
  const emptyRow=`<tr><td colspan="6" class="checkout-list-empty">${empty(S.products.length?'No products found':'Your shelves are ready',S.products.length?'Try another name, SKU, or category.':'Add your products and opening stock to get started.',managerAccess()?'new-product':'', 'Add a product')}</td></tr>`;
  $('#product-grid').innerHTML=`<table class="checkout-product-table" aria-label="Browse products"><colgroup><col class="checkout-col-sku"><col class="checkout-col-barcode"><col class="checkout-col-description"><col class="checkout-col-stock"><col class="checkout-col-price"><col class="checkout-col-add"></colgroup><thead><tr><th scope="col">SKU</th><th scope="col">Barcode</th><th scope="col">Description</th><th scope="col">Stock</th><th scope="col">Unit price</th><th scope="col">Add</th></tr></thead><tbody>${rows.length?rows.join(''):emptyRow}</tbody></table>`;
  $('#product-pager').innerHTML=pageCount>1?`<button type="button" data-product-page="previous" ${S.productPage===0?'disabled':''}>Previous</button><span>Page ${S.productPage+1} of ${pageCount}</span><button type="button" data-product-page="next" ${S.productPage===pageCount-1?'disabled':''}>Next</button>`:'';
}
function cartTotal(){return S.cart.reduce((total,l)=>total+(S.products.find(p=>p.product_id===l.product_id)?.amount_minor||0)*l.quantity,0);}
function cartPricing(){
  const subtotal=cartTotal(),rate=S.ticket?.discount_percent_bp||0;
  const refundableCapacity=S.cart.reduce((sum,l)=>{const p=S.products.find(p=>p.product_id===l.product_id);return sum+Math.max(0,((p?.amount_minor||0)-1)*l.quantity);},0);
  const discount=Math.min(Math.floor((subtotal*rate+5000)/10000),refundableCapacity);
  return {subtotal,discount,total:subtotal-discount};
}
function renderCart(){
  if(!$('#cart'))return;const units=S.cart.reduce((a,l)=>a+l.quantity,0);
  const pricing=cartPricing(),rate=S.ticket?.discount_percent_bp||0,rates=S.ticket?.discount_rates||[];
  $('#cart').innerHTML=`<div class="cart-header"><h2>Current order <span class="count-bubble">${units}</span></h2><button class="icon-btn" data-action="cancel-ticket" title="Cancel order" aria-label="Cancel order" ${!S.ticket?'disabled':''}>${icon('close')}</button></div><div class="cart-ticket"><span>${S.ticket?e(S.ticket.ticket_number):'A new order awaits'}</span><span>${e(S.user.display_name.split(' ')[0])}</span></div><div class="cart-lines">${S.cart.length?`<table class="cart-table" aria-label="Current order items"><colgroup><col class="cart-col-sku"><col class="cart-col-description"><col class="cart-col-quantity"><col class="cart-col-total"></colgroup><thead><tr><th scope="col">SKU</th><th scope="col">DESC</th><th scope="col" class="cart-quantity-cell">QTY</th><th scope="col" class="right">TOTAL</th></tr></thead><tbody>${S.cart.map(l=>{const p=S.products.find(p=>p.product_id===l.product_id);if(!p)return '';return `<tr><td class="cart-row-sku">${e(p.sku)}</td><td><button type="button" class="btn light small cart-view-description" data-action="view-cart-description" data-id="${p.product_id}" aria-label="View description for ${e(p.sku)}">View</button></td><td class="cart-quantity-cell"><div class="qty-control"><button type="button" data-qty="${p.product_id}" data-delta="-1" aria-label="Remove one ${e(p.description)}">−</button><button type="button" class="cart-set-quantity" data-action="set-cart-quantity" data-id="${p.product_id}" aria-label="Set total quantity for ${e(p.description)}">Qty ${l.quantity}</button><button type="button" data-qty="${p.product_id}" data-delta="1" aria-label="Add one ${e(p.description)}">+</button></div></td><td class="right cart-row-total">${money(p.amount_minor*l.quantity)}</td></tr>`;}).join('')}</tbody></table>`:`<div class="cart-empty"><p>A little empty for now.<br>Choose a product to start an order.</p></div>`}</div><div class="cart-summary"><div class="sum-row"><span>Subtotal</span><span>${money(pricing.subtotal)}</span></div>${rates.length?`<div class="cart-discount-choice"><label for="discount-choice">Discount</label><select id="discount-choice" aria-label="Order discount" ${cartPending||S.cartError?'disabled':''}><option value="0">No discount</option>${rates.map(r=>`<option value="${r.percent_bp}" ${rate===r.percent_bp?'selected':''}>${percentLabel(r.percent_bp)}</option>`).join('')}</select></div>`:''}${pricing.discount?`<div class="sum-row"><span>Discount (${percentLabel(rate)})</span><span>−${money(pricing.discount)}</span></div>`:''}<div class="sum-row"><span>Items</span><span>${units} ${units===1?'item':'items'}</span></div><div class="sum-row total"><span>Total amount</span><strong>${money(pricing.total)}</strong></div>${button('Review payment','pay','green','arrow',!S.cart.length||!S.shift||S.cartError?'disabled':'')}</div><div class="cart-foot">${S.cartError?'Cart needs a refresh before payment':S.ticket?'Saved to this ticket · Cash payment':'One ticket. One payment. One receipt.'}</div>`;
  if(S.ticket){const transfer=document.createElement('button');transfer.type='button';transfer.className='icon-btn';transfer.dataset.action='transfer-ticket';transfer.setAttribute('aria-label','Transfer this order');transfer.title='Transfer this order';transfer.innerHTML=icon('users');$('.cart-ticket').appendChild(transfer);}
  if(cartPending){$('.cart-foot').textContent='Saving this ticket…';$('[data-action=pay]').disabled=true;}
}
function viewCartDescription(pid){
  const product=S.products.find(p=>p.product_id===pid);
  requireClient(product,'Product details are unavailable. Refresh the counter.');
  modal('Product description',`<p class="description-sku">SKU: ${e(product.sku)}</p><div class="product-description-text">${e(product.description)}</div><p class="description-price">${money(product.amount_minor)} / ${e(product.unit)}</p><div class="modal-actions">${button('Close','close-modal','light')}</div>`);
}
function quantityKeypad(){
  return `<div class="quantity-keypad" role="group" aria-label="On-screen quantity keypad"><strong>Tap a quantity</strong>${['1','2','3','4','5','6','7','8','9','Clear','0','⌫'].map(value=>`<button type="button" data-quantity-key="${value}" aria-label="${value==='⌫'?'Delete last digit':value==='Clear'?'Clear quantity':value}">${value}</button>`).join('')}</div>`;
}
function wireQuantityKeypad(form,quantityInput){
  let replaceNextDigit=true;
  quantityInput.addEventListener('input',()=>{replaceNextDigit=false;});
  $('.quantity-keypad',form).addEventListener('click',ev=>{
    const key=ev.target.closest('[data-quantity-key]');
    if(!key)return;
    const value=key.dataset.quantityKey;
    if(value==='Clear')quantityInput.value='';
    else if(value==='⌫')quantityInput.value=quantityInput.value.slice(0,-1);
    else{
      const next=replaceNextDigit||quantityInput.value==='0'?value:quantityInput.value+value;
      if(next.length>7)return;
      quantityInput.value=next;
    }
    replaceNextDigit=false;
    quantityInput.dispatchEvent(new Event('input',{bubbles:true}));
    quantityInput.focus({preventScroll:true});
  });
}
async function productQuantityModal(pid){
  if(quantityDialogOpening||$('.modal')||S.paying)return;
  quantityDialogOpening=true;
  try{
    await cartQueue;
    requireClient(S.day&&S.shift,'Open the business day and your shift before starting a sale.');
    requireClient(!S.cartError,'Refresh the counter to recover the saved cart.');
    if(S.ticket)requireClient(!localStorage.getItem(`bazaar-pending-${S.user.user_id}-${S.ticket.purchase_ticket_id}`),'Review the previous payment result before changing this order.');
    const product=S.products.find(p=>p.product_id===pid),existing=S.cart.find(l=>l.product_id===pid)?.quantity||0;
    requireClient(product?.active,'This product is no longer available. Refresh the counter.');
    const available=product.quantity_on_hand-existing;
    requireClient(available>0,'All available stock for this item is already in the order.');
    const details=`<div class="quantity-product field full"><div class="cart-thumb">${productVisual(product)}</div><div class="quantity-product-price"><small>Unit price</small><strong>${money(product.amount_minor)} / ${e(product.unit)}</strong></div></div><div class="quantity-product-identifiers field full"><div><span>SKU</span><strong>${e(product.sku)}</strong></div><div><span>Barcode</span><strong>${e(product.barcode||'Not assigned')}</strong></div></div><div class="quantity-product-description field full"><span>Description</span><p>${e(product.description)}</p></div>`;
    formModal('Choose quantity',`<div class="quantity-main">${details}<div class="field full"><small>Available to add: ${available} ${e(product.unit)}.${existing?' Already in order: '+existing+' '+e(product.unit)+'.':''} Nothing is added until you confirm.</small></div>`+field('Quantity to add','quantity','number','1',`required min="1" max="${available}" step="1" inputmode="numeric"`)+`<div class="change-line" role="status" aria-live="polite"><span>Amount to add</span><strong id="quantity-add-total">${money(product.amount_minor)}</strong></div></div>`+quantityKeypad(),async data=>{
      const quantity=Number(data.quantity);
      requireClient(Number.isSafeInteger(quantity)&&quantity>=1,'Enter a whole quantity of at least 1.');
      requireClient(!S.cartError,'Refresh the counter to recover the saved cart.');
      await loadCatalog();
      const current=S.products.find(p=>p.product_id===pid),inOrder=S.cart.find(l=>l.product_id===pid)?.quantity||0;
      requireClient(current?.active,'This product is no longer available. Refresh the counter.');
      requireClient(quantity+inOrder<=current.quantity_on_hand,'That quantity exceeds the stock currently available. Reopen the product to review stock.');
      requireClient(current.amount_minor===product.amount_minor,'The selling price changed. Reopen the product to review its price.');
      await addProduct(pid,quantity);
      requireClient(!S.cartError,'The order could not be saved. Refresh the counter before trying again.');
      closeModal();renderProducts();toast(quantity+' × '+product.description+' added to the order.');
    },'Add to order',true);
    const form=$('#modal-form'),quantityInput=$('[name=quantity]',form),confirmButton=$('[type=submit]',form);
    form.classList.add('quantity-modal-form');
    wireQuantityKeypad(form,quantityInput);
    confirmButton.disabled=true;
    setTimeout(()=>{if(form.isConnected)confirmButton.disabled=false;},250);
    quantityInput.addEventListener('input',()=>{
      const quantity=Number(quantityInput.value);
      $('#quantity-add-total',form).textContent=Number.isSafeInteger(quantity)&&quantity>=1&&quantity<=available?money(quantity*product.amount_minor):'—';
    });
    quantityInput.select();
  }finally{quantityDialogOpening=false;}
}
async function setCartQuantityModal(pid){
  if(quantityDialogOpening||$('.modal')||S.paying)return;
  quantityDialogOpening=true;
  try{
    await cartQueue;
    requireClient(!S.cartError,'Refresh the counter to recover the saved cart.');
    requireClient(S.ticket&&!localStorage.getItem(`bazaar-pending-${S.user.user_id}-${S.ticket.purchase_ticket_id}`),'Review the previous payment result before changing this order.');
    const product=S.products.find(p=>p.product_id===pid),existing=S.cart.find(l=>l.product_id===pid)?.quantity||0;
    requireClient(product&&existing>0,'This item is no longer in the order. Refresh the counter.');
    const max=Math.min(product.quantity_on_hand,1_000_000);
    const details=`<div class="quantity-product field full"><div class="cart-thumb">${productVisual(product)}</div><div class="quantity-product-price"><small>Unit price</small><strong>${money(product.amount_minor)} / ${e(product.unit)}</strong></div></div><div class="quantity-product-identifiers field full"><div><span>SKU</span><strong>${e(product.sku)}</strong></div><div><span>Barcode</span><strong>${e(product.barcode||'Not assigned')}</strong></div></div><div class="quantity-product-description field full"><span>Description</span><p>${e(product.description)}</p></div>`;
    formModal('Set quantity',`<div class="quantity-main">${details}<div class="field full"><small>Set the total quantity for this item, not the amount to add. Current total: ${existing}. Available stock: ${max}. Enter 0 to remove it.</small></div>`+field('Total quantity in order','quantity','number',existing,`required min="0" max="${max}" step="1" inputmode="numeric"`)+`<div class="change-line" role="status" aria-live="polite"><span>New line total</span><strong id="quantity-set-total">${money(product.amount_minor*existing)}</strong></div></div>`+quantityKeypad(),async data=>{
      const quantity=Number(data.quantity);
      requireClient(Number.isSafeInteger(quantity)&&quantity>=0,'Enter a whole quantity of 0 or more.');
      await cartQueue;
      requireClient(!S.cartError,'Refresh the counter to recover the saved cart.');
      await loadCatalog();
      const current=S.products.find(p=>p.product_id===pid),inOrder=S.cart.find(l=>l.product_id===pid)?.quantity||0;
      requireClient(current&&inOrder>0,'This item is no longer in the order. Refresh the counter.');
      requireClient(quantity<=current.quantity_on_hand&&quantity<=1_000_000,'That quantity exceeds the stock currently available. Reopen Qty to review stock.');
      requireClient(quantity===0||current.active,'This product is no longer available. Refresh the counter.');
      requireClient(quantity===0||current.amount_minor===product.amount_minor,'The selling price changed. Reopen Qty to review its price.');
      if(quantity!==inOrder)await addProduct(pid,quantity-inOrder);
      requireClient(!S.cartError,'The order could not be saved. Refresh the counter before trying again.');
      closeModal();renderProducts();toast(quantity?`Total quantity set to ${quantity}.`:'Item removed from the order.');
    },'Set quantity',true);
    const form=$('#modal-form'),quantityInput=$('[name=quantity]',form);
    form.classList.add('quantity-modal-form');
    wireQuantityKeypad(form,quantityInput);
    quantityInput.addEventListener('input',()=>{
      const quantity=Number(quantityInput.value);
      $('#quantity-set-total',form).textContent=quantityInput.value!==''&&Number.isSafeInteger(quantity)&&quantity>=0&&quantity<=max?money(quantity*product.amount_minor):'—';
    });
    quantityInput.select();
  }finally{quantityDialogOpening=false;}
}
async function addProduct(pid,delta=1){
  if(S.paying)throw new Error('Finish the current payment before changing this order.');
  if(S.cartError)throw new Error('Refresh the counter to recover the saved cart.');
  if(!S.day||!S.shift)throw new Error('Open the business day and your shift before starting a sale.');
  const p=S.products.find(p=>p.product_id===pid);
  if(!p||(delta>0&&!p.active))throw new Error('This product is no longer available. Refresh the counter.');
  if(delta>0&&p.quantity_on_hand<=0)throw new Error('This product is out of stock.');
  if(!S.ticket){if(!creatingTicket)creatingTicket=api('/tickets','POST',{}).then(t=>{S.ticket=t;S.cart=t.lines.map(l=>({product_id:l.product_id,quantity:l.quantity}));}).finally(()=>creatingTicket=null);await creatingTicket;}
  if(localStorage.getItem(`bazaar-pending-${S.user.user_id}-${S.ticket.purchase_ticket_id}`))throw new Error('Review the previous payment result before changing this order.');
  const existing=S.cart.find(l=>l.product_id===pid);const qty=(existing?.quantity||0)+delta;
  if(!Number.isSafeInteger(qty)||qty<0||qty>1_000_000)throw new Error('Enter a valid whole quantity.');
  if(qty>p.quantity_on_hand)throw new Error('That quantity exceeds the stock currently available.');
  if(qty<=0)S.cart=S.cart.filter(l=>l.product_id!==pid);else if(existing)existing.quantity=qty;else S.cart.push({product_id:pid,quantity:qty});
  const snapshot=S.cart.map(l=>({...l}));cartPending++;renderCart();
  cartQueue=cartQueue.then(async()=>{try{if(!S.cartError)S.ticket=await api('/tickets/'+S.ticket.purchase_ticket_id,'PUT',{version:S.ticket.version,lines:snapshot});}catch(error){S.cartError=true;toast(error.message+' Refresh the counter to recover the saved cart.',true);}finally{cartPending--;renderCart();}});
  await cartQueue;
}
function askPaymentConfirmation(total,paid,ticketNumber,retry=false){
  return new Promise(resolve=>{
    const original=$('#modal-root .modal-overlay'),overlay=document.createElement('div');
    overlay.className='modal-overlay payment-confirm-overlay';
    overlay.innerHTML=`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="payment-confirm-title"><div class="modal-head payment-confirm-head"><h2 id="payment-confirm-title">Have you received the cash and checked the change?</h2><button type="button" class="icon-btn" aria-label="Close confirmation" data-payment-confirm="no">${icon('close')}</button></div><div class="modal-body"><p class="payment-confirm-ticket">${e(ticketNumber)}</p><dl class="payment-confirm-summary"><div><dt>Total amount</dt><dd>${money(total)}</dd></div><div><dt>Amount paid</dt><dd>${money(paid)}</dd></div><div><dt>Change due</dt><dd>${money(paid-total)}</dd></div></dl>${retry?'<p class="payment-confirm-note">Check or retry the previously submitted payment using the same request.</p>':''}<div class="payment-confirm-footer"><strong>Confirm payment?</strong><div class="modal-actions"><button type="button" class="btn light" data-payment-confirm="no">No</button><button type="button" class="btn green" data-payment-confirm="yes" disabled>Yes${icon('check')}</button></div></div></div></section>`;
    original.hidden=true;$('#modal-root').appendChild(overlay);
    let settled=false;
    const finish=confirmed=>{
      if(settled)return;settled=true;paymentConfirmationCancel=null;overlay.remove();original.hidden=false;
      if(!confirmed&&original.isConnected)$('#amount-paid',original)?.focus({preventScroll:true});
      resolve(confirmed);
    };
    paymentConfirmationCancel=()=>finish(false);
    overlay.addEventListener('click',ev=>{const choice=ev.target.closest('[data-payment-confirm]');if(choice&&!choice.disabled)finish(choice.dataset.paymentConfirm==='yes');});
    const yes=$('[data-payment-confirm=yes]',overlay);setTimeout(()=>{if(overlay.isConnected)yes.disabled=false;},250);
    $('.modal-actions [data-payment-confirm=no]',overlay).focus({preventScroll:true});
  });
}
async function paymentModal(){
  await cartQueue;if(S.cartError)throw new Error('Refresh the counter to recover the saved cart.');
  const q=await api('/tickets/'+S.ticket.purchase_ticket_id);S.ticket=q;
  if(q.sale_id){await showReceipt(q.sale_id);return;}
  requireClient(q.lines.length,'Add an item first.');
  const pendingKey=`bazaar-pending-${S.user.user_id}-${q.purchase_ticket_id}`;
  let pending;try{pending=JSON.parse(localStorage.getItem(pendingKey)||'null');}catch{pending=null;}
  const total=q.total_minor;
  modal('Complete this order',`<form id="payment-form" class="form-grid"><div class="payment-total field full"><small>${e(q.ticket_number)} · ${q.lines.reduce((a,l)=>a+l.quantity,0)} items</small><div class="sum-row"><span>Subtotal</span><span>${money(q.subtotal_minor)}</span></div>${q.discount_minor?`<div class="sum-row"><span>Discount (${percentLabel(q.discount_percent_bp)})</span><span>−${money(q.discount_minor)}</span></div>`:''}<strong>${money(total)}</strong><small>Cash payment · No added tax</small></div><div class="field full"><label for="amount-paid">Amount paid</label><input id="amount-paid" name="amount" type="text" inputmode="decimal" placeholder="0.00" value="${pending?(pending.tendered_minor/100).toFixed(2):''}" required autocomplete="off" ${pending?'readonly':''}></div><div class="quick-cash">${[total,...[10000,20000,50000,100000].filter(n=>n>total).slice(0,3)].map(n=>`<button type="button" data-cash="${n}" ${pending?'disabled':''}>${n===total?'Exact':money(n)}</button>`).join('')}</div><div class="change-line"><span>Change due</span><strong id="change-due">${money(pending?pending.tendered_minor-total:0)}</strong></div><div class="form-error" role="alert"></div><div class="field full"><small>${pending?'This payment was submitted before. Retrying will retrieve the same sale if it was saved.':'Check the amount before confirming. A receipt follows the saved sale.'}</small></div><div class="modal-actions">${button('Back','close-modal','light')}<button type="submit" class="btn green">${pending?'Check / retry payment':'Confirm payment'}${icon('check')}</button></div></form>`);
  if(q.duplicate_warning){const warning=document.createElement('div');warning.className='notice field full';warning.innerHTML=`<label class="check-field"><input id="duplicate-reviewed" type="checkbox" required ${pending?.duplicate_reviewed?'checked':''}><span>A matching order (${e(receiptNumber(q.duplicate_warning.receipt_number))}) was saved in the last two minutes. I checked that this is a separate customer purchase.</span></label>`;$('#payment-form').prepend(warning);}
  $('#amount-paid').addEventListener('input',()=>{try{$('#change-due').textContent=money(Math.max(0,minor($('#amount-paid').value)-total));}catch{$('#change-due').textContent='—';}});
  $('#payment-form').addEventListener('submit',async ev=>{
    ev.preventDefault();const form=ev.currentTarget,b=$('[type=submit]',form);if(b.disabled)return;b.disabled=true;$('.form-error',form).textContent='';
    try{
      const amount=minor($('#amount-paid').value);requireClient(amount>=total,'The amount paid is less than the total.');
      const body=pending||{request_key:key(),purchase_ticket_id:q.purchase_ticket_id,version:q.version,quote_hash:q.quote_hash,tendered_minor:amount,duplicate_reviewed:!!$('#duplicate-reviewed')?.checked};
      try{S.receiptPrinter=(await api('/receipt-printer')).printer;}catch{}
      if(!await askPaymentConfirmation(total,body.tendered_minor,q.ticket_number,!!pending))return;
      localStorage.setItem(pendingKey,JSON.stringify(body));pending=body;S.paying=true;
      const result=await api('/checkout','POST',body);localStorage.removeItem(pendingKey);S.paying=false;S.ticket=null;S.cart=[];
      await renderCheckout();await showReceipt(result.sale_id);toast(result.replayed?'Retrieved the existing sale.':'Payment saved. Check the receipt print status below.');
    }catch(error){
      S.paying=false;
      if(pending&&[400,403,409,429].includes(error.status)){
        localStorage.removeItem(pendingKey);pending=null;closeModal();await renderCheckout();toast(error.message+' Review the order before paying.',true);
      }else{
        $('.form-error',form).textContent=error.message;if($('#amount-paid'))$('#amount-paid').readOnly=!!pending;
      }
    }finally{b.disabled=false;}
  });
}
function requireClient(condition,message){if(!condition)throw new Error(message);}
function receiptCompanyHeader(){return `<header class="receipt-company-header"><img class="receipt-logo" src="/static/sqi-logo.png" alt="SQI logo" width="5442" height="3064"><h2>SQI Group Int'l Corp - Philippines</h2></header>`;}
function receiptCompanyFooter(){return `<footer class="receipt-company"><p>Head office: 18 Pineapple Rd, Malabon, 1475 Metro Manila, Philippines</p><div class="receipt-company-grid"><span>Tel: 8-364-7561</span><span>Website: <a href="https://sqigroup.ph" target="_blank" rel="noopener noreferrer">https://sqigroup.ph</a></span><span>Office Hours: 9:00 AM – 6:00 PM</span><span>Monday – Saturday</span></div></footer>`;}
async function showReceipt(sid){
  const r=await api('/sales/'+sid);currentReceipt=r;const s=r.sale,p=r.payment;
  modal('Acknowledgement receipt',`<div class="receipt-content">${receiptCompanyHeader()}<div class="receipt-heading"><p class="receipt-title">ACKNOWLEDGEMENT RECEIPT</p><p>${e(receiptNumber(s.receipt_number))}</p></div><div class="receipt-meta">Date: ${e(s.business_date)}<br>Cashier: ${e(s.display_name)}</div><table><thead><tr><th>ITEM</th><th class="right">AMOUNT</th></tr></thead><tbody>${r.lines.map(l=>`<tr><td>${e(l.short_description_snapshot||l.description_snapshot)}<br>${l.quantity} × ${money(l.unit_price_minor)}${l.discount_minor?`<br>Discount: −${money(l.discount_minor)}`:''}</td><td class="right">${money(l.line_total_minor)}</td></tr>`).join('')}</tbody></table>${s.discount_minor?`<div class="sum-row"><span>Subtotal</span><span>${money(s.subtotal_minor)}</span></div><div class="sum-row"><span>Discount (${percentLabel(s.discount_percent_bp)})</span><span>−${money(s.discount_minor)}</span></div>`:''}<div class="sum-row total"><span>TOTAL</span><strong>${money(s.total_minor)}</strong></div><div class="sum-row"><span>Cash paid</span><span>${money(p.tendered_minor)}</span></div><div class="sum-row"><span>Change</span><span>${money(p.change_minor)}</span></div><div class="receipt-thanks">Thank you for your purchase.</div>${receiptCompanyFooter()}</div>${r.corrections.length?`<div class="receipt-extra notice">${r.corrections.length} correction(s) linked · ${money(r.corrections.reduce((a,c)=>a+c.refund_total_minor,0))} refunded</div>`:''}<div class="modal-actions">${managerAccess()?button('Return / void','return-sale','light','refresh',`data-id="${sid}"`):''}${button('Print / save PDF','print-receipt','green','print',`data-id="${sid}"`)}</div>`);currentReceipt=r;
  await $('.receipt-logo').decode().catch(()=>{});
  void refreshReceiptPrintStatus(sid);
}
function openDay(continueToCheckout=false){const today=new Intl.DateTimeFormat('en-CA',{timeZone:S.bazaar?.timezone||'Asia/Manila',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());formModal('Open the next business day',field('Business date','business_date','date',today,'required')+approval(),async data=>{await api('/days/open','POST',data);closeModal();await boot();toast('The business day is open.');if(continueToCheckout)openShift(true);},'Open day');}
async function shiftOpenErrorMessage(error){
  if(error.status!==409||!error.message.startsWith('This operation conflicts with an existing record'))return error.message;
  try{
    const {shifts}=await api('/shifts?status=open');
    const here=shifts.find(s=>s.terminal_id===S.terminal?.terminal_id);
    if(here?.cashier_user_id===S.user?.user_id)return `Your shift #${here.shift_id} is already open here. Refresh the page to continue.`;
    if(here)return `Another cashier's shift is still open on this POS: ${here.display_name}, shift #${here.shift_id}.\n${managerAccess()?'Select Cancel, open Cashier shifts, count the drawer, and choose Manager close.':'Select Cancel and ask a manager to count and close it in Cashier shifts.'} Then open your shift. Signing out alone does not close a shift.`;
    const yours=shifts.find(s=>s.cashier_user_id===S.user?.user_id);
    if(yours)return `Your shift #${yours.shift_id} is still open on another POS. Finish any unpaid orders, count and close that shift there, then try again.`;
  }catch{}
  return `A cashier shift is already open for this account or POS.\n${managerAccess()?'Select Cancel, open Cashier shifts, count the drawer, and close the earlier shift.':'Select Cancel and ask a manager to check Cashier shifts, count the drawer, and close the earlier shift.'} Then try again. Signing out alone does not close a shift.`;
}
function openShift(continueToCheckout=false){formModal('Open your cashier shift',`<div class="field full"><small>Count the starting cash in this shift’s drawer. Only one shift can be open on this POS at a time.</small></div>`+field('Opening cash','opening_cash','text','0.00','required inputmode="decimal"'),async data=>{
  try{await api('/shifts/open','POST',{opening_cash_minor:minor(data.opening_cash)});}
  catch(error){throw new Error(await shiftOpenErrorMessage(error));}
  closeModal();await boot();toast('Your shift is open.');if(continueToCheckout)checkoutModePrompt();
},'Open shift');$('#modal-form').classList.add('shift-open-form');}
async function cancelTicket(){await cartQueue;if(!S.ticket)return;formModal('Cancel this order',`<div class="field full"><small>This cancels the open ticket. Completed sales use a manager-approved correction.</small></div>`+field('Reason','reason','text','','required'),async data=>{await api('/tickets/'+S.ticket.purchase_ticket_id+'/cancel','POST',{reason:data.reason,version:S.ticket.version});closeModal();S.ticket=null;S.cart=[];await renderCheckout();toast('Order cancelled.');},'Cancel order');}
async function transferTicket(){await cartQueue;if(!S.ticket)return;const {users}=await api('/filters');formModal('Transfer this order',selectField('Receiving cashier','target_user_id',users.filter(u=>u.user_id!==S.user.user_id).map(u=>[u.user_id,u.display_name]))+field('Reason','reason','text','','required')+`<div class="field full"><small>The receiving cashier must have an open shift and no current order. They can refresh their counter to retrieve this ticket.</small></div>`,async data=>{await api('/tickets/'+S.ticket.purchase_ticket_id+'/transfer','POST',{version:S.ticket.version,target_user_id:Number(data.target_user_id),reason:data.reason});closeModal();S.ticket=null;S.cart=[];await renderCheckout();toast('Order transferred. The receiving cashier can refresh their counter.');},'Transfer order');}
function productImportForm(){
  pendingProductImport=null;
  formModal('Add products from Excel',`<div class="notice field full">First upload the workbook to review its valid ITEM CODE and DESCRIPTION rows. Nothing is saved until you select Save all, set up later above the uploaded list.</div><div class="field full"><label for="f-workbook">Excel workbook</label><input id="f-workbook" name="workbook" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" required><small>Use an .xlsx file up to 6 MB. Repeated and existing SKUs are skipped.</small></div>`,async(data,form)=>{
    const file=$('[name=workbook]',form).files[0],upload=new FormData();upload.append('workbook',file);
    const result=await api('/products/import/preview','POST',upload,true);
    pendingProductImport={file,preview:result};
    const skipped=result.existing+result.duplicate_rows+result.rejected_rows;
    const summary=`${result.ready} new product${result.ready===1?'':'s'} ready${skipped?` · ${skipped} row${skipped===1?'':'s'} skipped`:''}`;
    modal('Uploaded products',`<div class="panel-title"><div><h2>${e(summary)}</h2><span class="muted">Review this list before saving</span></div><div class="actions">${button('Choose another file','bulk-upload-products','light','refresh')}${button('Save all, set up later','save-product-import','green','check',result.ready?'':'disabled')}</div></div>${result.products.length?table(['Excel row','SKU','Description'],result.products.map(p=>`<tr><td>${p.row}</td><td><strong>${e(p.sku)}</strong></td><td>${e(p.description)}</td></tr>`)):empty('No new products to save','Every valid SKU in this workbook already exists or was skipped.')}`,true);
  },'Show uploaded products',true);
}
async function savePendingProductImport(control){
  if(!pendingProductImport)return;
  control.disabled=true;
  try{
    const upload=new FormData();upload.append('workbook',pendingProductImport.file);
    const result=await api('/products/import','POST',upload,true);
    pendingProductImport=null;closeModal();await loadCatalog();await navigate('catalog');
    const skipped=result.existing+result.duplicate_rows+result.rejected_rows;
    toast(`${result.imported} product${result.imported===1?'':'s'} saved for later${skipped?`. ${skipped} row${skipped===1?' was':'s were'} skipped.`:'.'}`);
  }finally{control.disabled=false;}
}
async function productForm(pid,draftId){
  await loadCatalog();const p=S.products.find(p=>p.product_id===pid),draft=S.productDrafts.find(d=>d.product_import_draft_id===draftId);
  if(draftId&&!draft)throw new Error('This imported product is no longer available.');
  if(!S.categories.length){formModal('Create your first category',field('Category name','name','text','','required'),async data=>{await api('/categories','POST',data);closeModal();await productForm(pid,draftId);},'Create category');return;}
  const categoryOptions=(draft?[['','Choose category']]:[]).concat(S.categories.filter(c=>c.active).map(c=>[c.category_id,c.name]));
  const draftCategoryId=draft?S.categories.find(c=>c.name.toLocaleLowerCase()===draft.category_name?.toLocaleLowerCase())?.category_id||'':'';
  formModal(p?'Edit product':draft?'Update uploaded product':'Add a product',field('SKU','sku','text',p?.sku||draft?.sku||'','required maxlength="60"')+field('Barcode (optional)','barcode','text',p?.barcode||draft?.barcode||'','maxlength="80"')+`<div class="field full"><label for="f-description">Product description</label><input id="f-description" name="description" value="${e(p?.description||draft?.description||'')}" required maxlength="200"></div>`+field('Short description (optional)','short_description','text',p?.short_description||draft?.short_description||'','maxlength="120"')+selectField('Category','category_id',categoryOptions,p?.category_id||draftCategoryId)+field('Unit','unit','text',p?.unit||draft?.unit||'pc','required maxlength="20"')+field('Unit description (optional)','unit_description','text',p?.unit_description||draft?.unit_description||'','maxlength="80"')+field('Selling price','price','text',p?(p.amount_minor/100).toFixed(2):draft?.amount_minor?(draft.amount_minor/100).toFixed(2):'','required inputmode="decimal"')+(!p?field('Opening quantity','quantity','number','0','required min="0" max="1000000" step="1"'):'')+selectField('Availability','active',[['true','Active'],['false','Inactive']],String(p?!!p.active:true))+`<div class="field full"><label for="f-image">Product photo (optional)</label><input id="f-image" name="image" type="file" accept="image/jpeg,image/png,image/webp"><small>JPEG, PNG, or WebP. Up to 5 MB and 12 megapixels.</small></div>`+(p?`<div class="field full" id="price-change-reason" hidden><label for="f-reason">Reason for price change</label><input id="f-reason" name="reason" maxlength="300" placeholder="For example, supplier cost changed" disabled><small>Required only when changing an existing selling price.</small></div>`:''),async(data,form)=>{
    const body={...data,draft_id:draftId,category_id:Number(data.category_id),active:data.active==='true',
      unit_price_minor:minor(data.unit_price),selling_price_minor:minor(data.price)};
    if(!p){form.dataset.requestKey ||= key();body.quantity=Number(data.quantity);body.request_key=form.dataset.requestKey;}
    const result=await api(p?'/products/'+pid:'/products',p?'PUT':'POST',body);
    const image=$('[name=image]',form).files[0];
    if(image){const upload=new FormData();upload.append('image',image);try{await api('/products/'+result.product_id+'/image','POST',upload,true);}catch(error){toast('Product saved. Photo upload failed: '+error.message,true);closeModal();await loadCatalog();await navigate('catalog');return;}}
    closeModal();await loadCatalog();await navigate('catalog');toast(draft?'Uploaded product set up.':'Product saved.');
  },'Save product',true);
  const unitPrice=p?.unit_price_minor??draft?.unit_price_minor??draft?.amount_minor;
  const unitField=field(p?'Unit price (locked)':'Unit price','unit_price','text',
    unitPrice?(unitPrice/100).toFixed(2):'',p?'readonly aria-readonly="true"':'required inputmode="decimal"');
  $('#f-price').parentElement.insertAdjacentHTML('beforebegin',unitField);
  $('#f-unit_price').parentElement.insertAdjacentHTML('beforeend',
    `<small>${p?'Original company price. This field is locked after product setup.':'Original company price. It will be locked after saving.'}</small>`);
  if(!p){
    const unitInput=$('#f-unit_price'),sellingInput=$('#f-price');
    let sellingEdited=false;
    sellingInput.addEventListener('input',()=>{sellingEdited=true;});
    unitInput.addEventListener('input',()=>{if(!sellingEdited)sellingInput.value=unitInput.value;});
  }
  const productBarcode=$('#f-barcode');
  productBarcode.placeholder='Type or scan the label barcode';
  productBarcode.autocomplete='off';
  productBarcode.parentElement.insertAdjacentHTML('beforeend','<small>Click this field and scan the label, or type its barcode. Each product needs a unique code.</small>');
  if(p){
    const form=$('#modal-form'),priceInput=$('[name=price]',form),reasonGroup=$('#price-change-reason',form),reasonInput=$('[name=reason]',form);
    const updatePriceReason=()=>{let changed=false;try{changed=minor(priceInput.value)!==p.amount_minor;}catch{}reasonGroup.hidden=!changed;reasonInput.required=changed;reasonInput.disabled=!changed;};
    priceInput.addEventListener('input',updatePriceReason);priceInput.addEventListener('change',updatePriceReason);updatePriceReason();
  }
}
function catalogPager(kind,page,total,pageSize){
  if(!total)return '';
  const pages=Math.max(1,Math.ceil(total/pageSize));
  const first=(page-1)*pageSize+1,last=Math.min(page*pageSize,total);
  const label=kind==='drafts'?'Saved product pages':'Catalog pages';
  return `<nav class="catalog-pager" aria-label="${label}"><button type="button" class="btn light small" data-action="catalog-page" data-kind="${kind}" data-step="-1" ${page<=1?'disabled':''}>Previous</button><span>${num(first)}–${num(last)} of ${num(total)} · Page ${page} of ${pages}</span><button type="button" class="btn light small" data-action="catalog-page" data-kind="${kind}" data-step="1" ${page>=pages?'disabled':''}>Next</button></nav>`;
}
async function renderCatalog(reload=true){
  if(reload)await loadCatalog();
  const drafts=S.productDrafts||[],pageSize=10,needle=catalogSearch.trim().toLocaleLowerCase();
  const matches=item=>!needle||[item.sku,item.barcode,item.description,item.short_description,item.category_name].some(value=>String(value||'').toLocaleLowerCase().includes(needle));
  const matchingDrafts=drafts.filter(matches),matchingProducts=S.products.filter(matches);
  catalogDraftPage=Math.min(catalogDraftPage,Math.max(1,Math.ceil(matchingDrafts.length/pageSize)));
  catalogProductPage=Math.min(catalogProductPage,Math.max(1,Math.ceil(matchingProducts.length/pageSize)));
  const visibleDrafts=matchingDrafts.slice((catalogDraftPage-1)*pageSize,catalogDraftPage*pageSize);
  const visibleProducts=matchingProducts.slice((catalogProductPage-1)*pageSize,catalogProductPage*pageSize);
  const draftRows=visibleDrafts.map(d=>`<tr><td><strong>${e(d.sku)}</strong></td><td class="catalog-description" title="${e(d.description)}"><strong>${e(d.description)}</strong>${d.short_description&&d.short_description.trim().toLocaleLowerCase()!==d.description.trim().toLocaleLowerCase()?`<small>${e(d.short_description)}</small>`:''}</td><td>${e(d.category_name||'—')}</td><td>${d.unit_price_minor?money(d.unit_price_minor):'—'}</td><td>${pill(d.import_issue||'Set up later','warn')}</td><td>${button('Set up','complete-product','green small','edit',`data-id="${d.product_import_draft_id}"`)}</td></tr>`);
  const productRows=visibleProducts.map(p=>`<tr><td><div class="table-product"><div class="cart-thumb">${productVisual(p)}</div><div class="catalog-product-text" title="${e(p.description)}"><strong>${e(p.description)}</strong><small>${e(p.sku)}${p.barcode?' · '+e(p.barcode):''}${p.short_description&&p.short_description.trim().toLocaleLowerCase()!==p.description.trim().toLocaleLowerCase()?' · '+e(p.short_description):''}</small></div></div></td><td>${e(p.category_name)}</td><td>${money(p.unit_price_minor)}</td><td>${money(p.selling_price_minor??p.amount_minor)}</td><td>${p.quantity_on_hand} ${e(p.unit)}</td><td>${pill(p.active?'Active':'Inactive',p.active?'success':'warn')}</td><td>${button('Edit','edit-product','light small','edit',`data-id="${p.product_id}"`)}</td></tr>`);
  const searchForm=`<form id="catalog-search" class="catalog-search" role="search"><label for="catalog-query">Search all products</label><div class="catalog-search-controls"><input id="catalog-query" type="search" value="${e(catalogSearch)}" placeholder="SKU, barcode, description or category" maxlength="120" autocomplete="off"><button class="btn green" type="submit">${icon('search')}Search</button>${catalogSearch?button('Clear','catalog-clear-search','light small','close'):''}</div></form>`;
  const draftPanel=drafts.length?`<section class="panel catalog-panel catalog-drafts"><div class="panel-title"><h2>Products saved for later <span class="count-bubble">${num(drafts.length)}</span></h2><span class="muted">${catalogSearch?`${num(matchingDrafts.length)} matching`:'Added and saved · set up anytime'}</span></div>${draftRows.length?table(['SKU','Description','Category','Unit price','Status',''],draftRows):empty('No saved products match','Try another search.')}${catalogPager('drafts',catalogDraftPage,matchingDrafts.length,pageSize)}</section>`:'';
  const productPanel=`<section class="panel catalog-panel catalog-products"><div class="panel-title"><h2>Product catalog <span class="count-bubble">${num(S.products.length)}</span></h2><span class="muted">${catalogSearch?`${num(matchingProducts.length)} matching`:'Unit price is locked; selling price can change'}</span></div>${productRows.length?table(['Product','Category','Unit price','Selling price','On hand','Status',''],productRows):S.products.length?empty('No products match','Try another search.'):empty('Start with your first product','Add one product or upload an Excel product list.','new-product','Add product')}${catalogPager('products',catalogProductPage,matchingProducts.length,pageSize)}</section>`;
  $('#page').innerHTML=heading('Your products','A home for everything on your shelf.',button('New category','new-category','light','plus')+button('Add from Excel','bulk-upload-products','light','download')+button('Add product','new-product','green','plus'))+searchForm+draftPanel+productPanel;
  $('#catalog-search').addEventListener('submit',async ev=>{ev.preventDefault();catalogSearch=$('#catalog-query').value.trim();catalogDraftPage=1;catalogProductPage=1;try{await renderCatalog(false);}catch(error){toast(error.message,true);}});
}
function stockForm(){
  const products=S.products;
  if(!products.length)return productForm();
  const byId=new Map(products.map(p=>[p.product_id,p]));
  const selected=new Set(),quantities=new Map();
  let kind='in',search='',page=0,reference='',pendingPayload=null;
  const pageSize=40;
  const kindName=()=>kind==='opening'?'Opening stock':'Stock in';
  const available=()=>products.filter(p=>kind!=='opening'||!p.has_stock_history);
  const errorAt=form=>$('.form-error',form);
  const setModal=(body)=>{modal('Record stock movement',body,true);$('.modal').classList.add('stock-modal');};
  function selectStep(){
    const legend=`<div class="stock-legend"><strong>What each movement type means</strong><div class="stock-legend-grid"><div class="stock-legend-item ${kind==='in'?'selected':''}"><strong>Stock in</strong><span>Add items you received, such as a new delivery.</span></div><div class="stock-legend-item ${kind==='opening'?'selected':''}"><strong>Opening stock</strong><span>Enter the first quantity for items with no stock history yet.</span></div></div></div>`;
    setModal(`<div class="stock-step">Step 1 of 2 · Select items</div><form id="stock-select-form"><div class="form-grid">${selectField('Movement type','document_type',[['in','Stock in'],['opening','Opening stock']],kind)}${legend}<div class="field full"><label for="stock-search">Find products by name, SKU, or barcode</label><input id="stock-search" type="search" autocomplete="off" placeholder="Search your products" value="${e(search)}"></div></div><div class="stock-picker-head"><strong id="stock-selected-count"></strong><span id="stock-result-count"></span></div><div id="stock-picker" class="stock-picker"></div><div id="stock-picker-pages" class="stock-picker-pages"></div><div class="form-error" role="alert"></div><div class="modal-actions">${button('Cancel','close-modal','light')}<button type="submit" class="btn green" id="stock-continue">Continue ${icon('arrow')}</button></div></form>`);
    const form=$('#stock-select-form'),picker=$('#stock-picker'),pager=$('#stock-picker-pages');
    const updateCount=()=>{const count=selected.size;$('#stock-selected-count',form).textContent=`${count} of 200 items selected`;$('#stock-continue',form).disabled=!count;};
    function showProducts(){
      const needle=search.trim().toLocaleLowerCase();
      const matches=available().filter(p=>`${p.sku} ${p.description} ${p.barcode||''}`.toLocaleLowerCase().includes(needle));
      const pages=Math.max(1,Math.ceil(matches.length/pageSize));page=Math.min(page,pages-1);
      $('#stock-result-count',form).textContent=`${num(matches.length)} matching products`;
      picker.innerHTML=matches.length?matches.slice(page*pageSize,(page+1)*pageSize).map(p=>`<label class="stock-picker-row"><input type="checkbox" value="${p.product_id}" ${selected.has(p.product_id)?'checked':''}><span><strong>${e(p.description)}</strong><small>${e(p.sku)}${p.barcode?' · '+e(p.barcode):''}</small></span><em>${num(p.quantity_on_hand)} on hand</em></label>`).join(''):`<p class="stock-picker-empty">${kind==='opening'&&!needle?'All products already have stock history. Choose Stock in for deliveries.':'No products match this search.'}</p>`;
      pager.innerHTML=`<button type="button" class="btn light" data-stock-page="previous" ${page===0?'disabled':''}>Previous</button><span>Page ${page+1} of ${pages}</span><button type="button" class="btn light" data-stock-page="next" ${page>=pages-1?'disabled':''}>Next</button>`;
      updateCount();
    }
    $('[name=document_type]',form).addEventListener('change',ev=>{kind=ev.target.value;selected.clear();quantities.clear();page=0;selectStep();});
    $('#stock-search',form).addEventListener('input',ev=>{search=ev.target.value;page=0;showProducts();});
    picker.addEventListener('change',ev=>{if(ev.target.type!=='checkbox')return;const id=Number(ev.target.value);if(ev.target.checked){if(selected.size>=200){ev.target.checked=false;errorAt(form).textContent='Choose up to 200 items at a time.';return;}selected.add(id);}else{selected.delete(id);quantities.delete(id);}errorAt(form).textContent='';updateCount();});
    pager.addEventListener('click',ev=>{const direction=ev.target.closest('[data-stock-page]')?.dataset.stockPage;if(!direction)return;page+=direction==='next'?1:-1;showProducts();picker.scrollTop=0;});
    form.addEventListener('submit',ev=>{ev.preventDefault();if(!selected.size){errorAt(form).textContent='Select at least one item.';return;}reviewStep();});
    showProducts();
  }
  function reviewStep(){
    const items=[...selected].map(id=>byId.get(id)).filter(Boolean).sort((a,b)=>a.description.localeCompare(b.description));
    setModal(`<div class="stock-step">Step 2 of 2 · Review quantities</div><form id="stock-review-form"><p class="stock-review-intro">${kindName()} · ${items.length} ${items.length===1?'item':'items'}. Enter how many units to add beside each item.</p><div class="stock-review-list"><div class="stock-review-head"><span>Item</span><span>On hand</span><span>${kind==='opening'?'Starting qty':'Qty to add'}</span></div>${items.map(p=>`<div class="stock-review-row"><label for="stock-qty-${p.product_id}"><strong>${e(p.description)}</strong><small>${e(p.sku)}</small></label><span>${num(p.quantity_on_hand)}</span><input id="stock-qty-${p.product_id}" name="quantity-${p.product_id}" type="number" inputmode="numeric" step="1" min="1" max="1000000" required value="${quantities.get(p.product_id)||''}" aria-label="Quantity for ${e(p.description)}"></div>`).join('')}</div><div class="stock-review-total" id="stock-review-total"></div><div class="form-grid">${field('Reference number (optional)','reference_no','text',reference,'maxlength="80"')}${approval()}</div><div class="stock-warning" role="note"><strong>Review before saving.</strong> These quantities will be added to stock together. Posting creates a permanent stock record and cannot be undone here. Check every item and quantity carefully.</div><label class="stock-confirm"><input type="checkbox" name="reviewed" required> I checked all items and quantities and understand this posting cannot be undone.</label><div class="form-error" role="alert"></div><div class="modal-actions"><button type="button" class="btn light" id="stock-back">Back to items</button><button type="submit" class="btn green">Post ${items.length} ${items.length===1?'item':'items'} ${icon('arrow')}</button></div></form>`);
    const form=$('#stock-review-form');
    const lines=()=>items.map(p=>({product_id:p.product_id,quantity:Number($(`[name="quantity-${p.product_id}"]`,form).value)}));
    const updateTotal=()=>{const values=lines();const valid=values.every(l=>Number.isSafeInteger(l.quantity)&&l.quantity>=1&&l.quantity<=1000000);$('#stock-review-total',form).textContent=valid?`${num(values.reduce((sum,l)=>sum+l.quantity,0))} total units will be added across ${items.length} items`:'Enter a positive whole-number quantity for every item.';};
    form.addEventListener('input',ev=>{if(ev.target.type==='number'){quantities.set(Number(ev.target.name.slice(9)),ev.target.value);updateTotal();}if(ev.target.name==='reference_no')reference=ev.target.value;});
    $('#stock-back',form).addEventListener('click',()=>{if(pendingPayload){errorAt(form).textContent='The last request may have posted. Check movement history before changing this list.';return;}selectStep();});
    form.addEventListener('submit',async ev=>{
      ev.preventDefault();if(!form.reportValidity())return;
      const stockLines=lines();if(!stockLines.every(l=>Number.isSafeInteger(l.quantity)&&l.quantity>=1&&l.quantity<=1000000)){errorAt(form).textContent='Enter a positive whole-number quantity for every item.';return;}
      const body={document_type:kind,reference_no:reference.trim(),manager_password:$('[name=manager_password]',form).value,lines:stockLines};
      if(pendingPayload){const prior=pendingPayload;const same=JSON.stringify({...prior,request_key:undefined})===JSON.stringify({...body,request_key:undefined});if(!same){errorAt(form).textContent='The last request may have posted. Retry without changing the details, then check movement history.';return;}}
      else pendingPayload={...body,request_key:key()};
      const submit=$('[type=submit]',form);submit.disabled=true;errorAt(form).textContent='';
      try{await api('/stock','POST',pendingPayload);closeModal();await loadCatalog();await renderInventory();toast(`${items.length} stock ${items.length===1?'item':'items'} posted together.`);}
      catch(error){errorAt(form).textContent=error.message;if(error.status)pendingPayload=null;}
      finally{submit.disabled=false;}
    });
    updateTotal();
  }
  selectStep();
}
function inventoryPager(kind,page,total,size){
  const pages=Math.max(1,Math.ceil(total/size)),first=total?(page-1)*size+1:0,last=Math.min(page*size,total);
  return `<nav class="inventory-pager" aria-label="${kind==='product'?'Product':'Movement'} pages"><span>${num(first)}–${num(last)} of ${num(total)} · Page ${page} of ${pages}</span><div>${button('Previous','inventory-page','light','','data-kind="'+kind+'" data-step="-1" '+(page<=1?'disabled':''))}${button('Next','inventory-page','light','','data-kind="'+kind+'" data-step="1" '+(page>=pages?'disabled':''))}</div></nav>`;
}
async function renderInventory(){
  const renderId=++inventoryRenderId;
  const query=new URLSearchParams({q:inventoryFilters.q,category_id:inventoryFilters.category_id,from:inventoryFilters.from,to:inventoryFilters.to,product_page:String(inventoryFilters.product_page),movement_page:String(inventoryFilters.movement_page)});
  if(inventoryEventId)query.set('event_id',String(inventoryEventId));
  const data=await api('/inventory?'+query);
  if(renderId!==inventoryRenderId||S.page!=='inventory')return;
  inventoryFilters.product_page=data.product_page;inventoryFilters.movement_page=data.movement_page;
  const s=data.summary,view=inventoryFilters.view;
  const stockMoney=n=>new Intl.NumberFormat('en',{style:'currency',currency:data.currency_code||'PHP'}).format((n||0)/100);
  const categories=S.categories.map(c=>`<option value="${c.category_id}" ${String(c.category_id)===inventoryFilters.category_id?'selected':''}>${e(c.name)}</option>`).join('');
  const filterForm=`<form class="inventory-filters" id="inventory-filters"><label>Product or SKU<input name="q" type="search" value="${e(inventoryFilters.q)}" placeholder="Search name, SKU, barcode" maxlength="120"></label><label>Category<select name="category_id"><option value="">All categories</option>${categories}</select></label><label>Posted from<input name="from" type="date" value="${e(inventoryFilters.from)}"></label><label>Posted to<input name="to" type="date" value="${e(inventoryFilters.to)}"></label><div class="inventory-filter-actions"><button class="btn green" type="submit">Apply</button>${button('Clear','inventory-clear','light')}</div></form>`;
  const metrics=`<div class="inventory-metrics"><div><span>Closing units</span><strong>${num(s.closing)}</strong><small>${inventoryFilters.to?'As of end date':'On hand now'}</small></div><div><span>Stock added</span><strong>+${num(s.added)}</strong><small>Opening stock and receipts</small></div><div><span>Units sold</span><strong>−${num(s.sold)}</strong><small>Completed sales</small></div><div><span>Restocked</span><strong>+${num(s.restocked)}</strong><small>Sellable returns</small></div></div><div class="inventory-summary-strip"><span><strong>${num(s.products)}</strong> products</span><span><strong>${num(s.zero_products)}</strong> at zero stock</span><span><strong>${num(s.low_products)}</strong> low stock</span><span><strong>${stockMoney(s.retail_value_minor)}</strong> at current selling prices</span></div>`;
  const tabs=`<div class="inventory-tabs" role="tablist" aria-label="Inventory views">${[['products','By product',data.product_total],['categories','By category',data.categories.length],['movements','Movements',data.movement_total]].map(([id,label,count])=>`<button type="button" role="tab" aria-selected="${view===id}" class="${view===id?'active':''}" data-action="inventory-view" data-view="${id}">${label}<span>${num(count)}</span></button>`).join('')}</div>`;
  const numberHeader=label=>`<span class="inventory-number-head">${label}</span>`;
  let detail='';
  if(view==='products'){
    const rows=data.products.map(p=>`<tr><td><strong>${e(p.description)}</strong><small>${e(p.sku)} · ${e(p.unit)}</small></td><td>${e(p.category_name)}</td><td class="numeric">${num(p.opening)}</td><td class="numeric">+${num(p.added)}</td><td class="numeric">−${num(p.sold)}</td><td class="numeric">+${num(p.restocked)}</td><td class="numeric strong">${num(p.closing)}</td><td>${!p.active?'<span class="inventory-status muted">Inactive</span>':p.closing===0?'<span class="inventory-status danger">Out</span>':p.closing<6?'<span class="inventory-status warn">Low</span>':'<span class="inventory-status">In stock</span>'}</td></tr>`);
    detail=`<section class="panel inventory-detail"><div class="panel-title"><h2>Product balances</h2><span class="muted">${num(data.product_total)} matching products</span></div>${rows.length?table(['Product','Category',...['Opening','Added','Sold','Restocked','Closing'].map(numberHeader),'Status'],rows):`<div class="inventory-empty">No products match these filters.</div>`}${inventoryPager('product',data.product_page,data.product_total,data.product_page_size)}</section>`;
  }else if(view==='categories'){
    const rows=data.categories.map(c=>`<tr><td><button type="button" class="inventory-drill" data-action="inventory-category" data-id="${c.category_id}">${e(c.category_name)} ${icon('arrow')}</button></td><td class="numeric">${num(c.products)}</td><td class="numeric">${num(c.opening)}</td><td class="numeric">+${num(c.added)}</td><td class="numeric">−${num(c.sold)}</td><td class="numeric">+${num(c.restocked)}</td><td class="numeric strong">${num(c.closing)}</td><td class="numeric">${num(c.zero_products)}</td></tr>`);
    detail=`<section class="panel inventory-detail"><div class="panel-title"><h2>Category balances</h2><span class="muted">Select a category to see its products</span></div>${rows.length?table(['Category',...['Products','Opening','Added','Sold','Restocked','Closing','At zero'].map(numberHeader)],rows):`<div class="inventory-empty">No categories match these filters.</div>`}</section>`;
  }else{
    const labels={sale:'Sold',restock:'Restocked',opening:'Opening stock',received:'Stock received'};
    const rows=data.movements.map(m=>`<tr><td>${e(timestamp(m.created_at))}<small>${m.day_number?'Day '+num(m.day_number):'Before Day 1'}</small></td><td><strong>${e(m.description)}</strong><small>${e(m.sku)} · ${e(m.category_name)}</small></td><td>${e(labels[m.movement_type]||m.movement_type)}</td><td class="numeric strong ${m.quantity_change>0?'positive':''}">${m.quantity_change>0?'+':''}${num(m.quantity_change)}</td><td>${e(receiptNumber(m.reference_no)||'—')}</td><td>${e(m.display_name)}</td><td>${e(m.reason||'—')}</td></tr>`);
    detail=`<section class="panel inventory-detail"><div class="panel-title"><h2>Stock movements</h2><span class="muted">All matching records · newest first</span></div>${rows.length?table(['Posted','Product','Type',numberHeader('Units'),'Reference','Recorded by','Reason'],rows):`<div class="inventory-empty">No movements match these filters.</div>`}${inventoryPager('movement',data.movement_page,data.movement_total,data.movement_page_size)}</section>`;
  }
  const period=inventoryFilters.from||inventoryFilters.to?`${inventoryFilters.from||'First record'} to ${inventoryFilters.to||'now'}`:'All posting dates';
  $('#page').innerHTML=`<div class="inventory-page">${heading(inventoryEventId?'Archived inventory: '+archiveEventName:'Inventory','Balances and every stock movement, in one place.',inventoryEventId?button('Current event','current-inventory','light','refresh'):button('Record movement','new-stock','green','plus'))}${filterForm}<div class="inventory-period">${e(period)} · ${e(data.timezone)} local posting time</div>${metrics}${tabs}${detail}<p class="inventory-help">Closing = Opening + Added + Restocked − Sold. A return changes stock only when sellable units are restocked. Date filters use posting time; the business day appears beside each movement. Retail value uses current selling prices.</p></div>`;
  const form=$('#inventory-filters');
  form.addEventListener('submit',async ev=>{ev.preventDefault();const values=Object.fromEntries(new FormData(form));Object.assign(inventoryFilters,values,{product_page:1,movement_page:1});try{await renderInventory();}catch(error){toast(error.message,true);}});
  $$('select,input[type=date]',form).forEach(control=>control.addEventListener('change',()=>form.requestSubmit()));
}

function queryString(){const params=new URLSearchParams(Object.entries(S.filters).filter(([,v])=>v));if(S.page==='reports'&&reportEventId)params.set('event_id',String(reportEventId));return params.toString();}
async function filterBar(){const f=await api('/filters'+(S.page==='reports'&&reportEventId?'?event_id='+reportEventId:''));return `<div class="filters"><label>Business day<select data-filter="day_id"><option value="">All days</option>${f.days.map(d=>`<option value="${d.bazaar_day_id}" ${S.filters.day_id==d.bazaar_day_id?'selected':''}>Day ${d.day_number} · ${e(d.business_date)}</option>`).join('')}</select></label><label>From<input type="date" data-filter="from" value="${e(S.filters.from||'')}"></label><label>To<input type="date" data-filter="to" value="${e(S.filters.to||'')}"></label>${managerAccess()?`<label>Cashier<select data-filter="user_id"><option value="">All cashiers</option>${f.users.map(u=>`<option value="${u.user_id}" ${S.filters.user_id==u.user_id?'selected':''}>${e(u.display_name)}</option>`).join('')}</select></label>`:''}<label>Category<select data-filter="category_id"><option value="">All categories</option>${S.categories.map(c=>`<option value="${c.category_id}" ${S.filters.category_id==c.category_id?'selected':''}>${e(c.name)}</option>`).join('')}</select></label><label>Product<select data-filter="product_id"><option value="">All products</option>${S.products.map(p=>`<option value="${p.product_id}" ${S.filters.product_id==p.product_id?'selected':''}>${e(p.sku+' · '+p.description)}</option>`).join('')}</select></label></div>`;}
async function renderTransactions(){
  const params=new URLSearchParams(queryString());
  params.set('q',transactionSearch);
  params.set('page',String(transactionPage));
  const [filters,{sales,total,page,page_size}]=await Promise.all([filterBar(),api('/sales?'+params)]);
  transactionPage=page;
  const pages=Math.max(1,Math.ceil(total/page_size));
  const start=total?(page-1)*page_size+1:0;
  const end=total?Math.min(page*page_size,total):0;
  const rows=sales.map(s=>`<tr><td class="mono">${e(receiptNumber(s.receipt_number))}</td><td>Day ${s.day_number} · ${e(timestamp(s.completed_at))}</td><td>${e(s.display_name)}</td><td><strong>${money(s.total_minor)}</strong></td><td>${s.refunded_minor?money(s.refunded_minor):'—'}</td><td>${button('View receipt','view-receipt','light small','receipt',`data-id="${s.sale_id}"`)}</td></tr>`);
  $('#page').innerHTML=heading('Every sale has a story.','Open a receipt to review its items, payment, and linked corrections.',button('Clear filters','clear-filters','light','refresh'))+filters+`<div class="panel transaction-panel"><div class="panel-title"><h2>Transaction history</h2><span class="muted">${num(total)} matching ${total===1?'sale':'sales'}</span></div><form id="transaction-search" class="transaction-search" role="search"><label for="transaction-query">Search sales</label><div class="transaction-search-controls"><input id="transaction-query" type="search" value="${e(transactionSearch)}" placeholder="Receipt, cashier, product or SKU" maxlength="120" autocomplete="off"><button class="btn green" type="submit">${icon('search')}Search</button></div></form>${rows.length?table(['Receipt','Day / time','Cashier','Total','Refunded',''],rows):empty('No sales in this view','Try another search or change the filters.')}<nav class="transaction-pager" aria-label="Transaction pages"><button type="button" class="btn light small" data-action="transaction-page" data-step="-1" ${page<=1?'disabled':''}>Previous</button><span>${num(start)}–${num(end)} of ${num(total)} · Page ${page} of ${pages}</span><button type="button" class="btn light small" data-action="transaction-page" data-step="1" ${page>=pages?'disabled':''}>Next</button></nav></div>`;
  $('#transaction-search').addEventListener('submit',async ev=>{ev.preventDefault();transactionSearch=$('#transaction-query').value.trim();transactionPage=1;try{await renderTransactions();}catch(error){toast(error.message,true);}});
}
async function renderReports(){const filters=await filterBar();const r=await api('/reports?'+queryString());const t=r.summary;const reportMoney=n=>new Intl.NumberFormat('en',{style:'currency',currency:r.currency_code||'PHP'}).format((n||0)/100);
  const unitLabel=(count,action)=>`${num(count)} ${count===1?'unit':'units'} ${action}`;
  const reportTable=(title,rows)=>`<div class="panel"><div class="panel-title"><h2>${title}</h2></div>${rows.length?table(['Description','Unit counts','Sales','Refunds','Net'],rows.map(r=>`<tr><td><strong>${e(r.label)}</strong></td><td><div class="report-unit-count"><strong>${unitLabel(r.units,'sold')}</strong>${r.returned_units?`<span>${unitLabel(r.returned_units,'returned or voided')}</span>`:''}</div></td><td>${reportMoney(r.sales_minor)}</td><td>${reportMoney(r.refunds_minor)}</td><td><strong>${reportMoney(r.sales_minor-r.refunds_minor)}</strong></td></tr>`)):empty('No activity in this view','Sales and returns will appear here.')}</div>`;
  $('#page').innerHTML=heading(reportEventId?'Archived report: '+archiveEventName:'A good look at your day.','Follow the numbers from each business day to every item.',(reportEventId?button('Current event','current-report','light','refresh'):'')+button('Clear filters','clear-filters','light','refresh')+`<a class="btn green" href="/api/reports?${queryString()}&format=xlsx">${icon('download')}Download Excel report</a>`)+filters+`<div class="stats"><div class="stat featured"><label>Net sales ${icon('chart')}</label><div class="value">${reportMoney(t.net_minor)}</div><small>Sales less refunds in this date range</small></div><div class="stat"><label>Gross sales</label><div class="value">${reportMoney(t.gross_minor)}</div><small>${unitLabel(t.units,'sold')} · ${t.transactions} transactions</small></div><div class="stat"><label>Refunds</label><div class="value">${reportMoney(t.refunds_minor)}</div><small>${unitLabel(t.returned_units,'returned or voided')}</small></div><div class="stat"><label>Average sale</label><div class="value">${reportMoney(t.transactions?Math.round(t.sales_minor/t.transactions):0)}</div><small>Completed sale value per transaction</small></div></div>`+reportTable('By business day',r.days)+`<div class="two-col">${reportTable('By category',r.categories)}${reportTable('By cashier',r.cashiers)}</div>`+reportTable('By product',r.items)+`<p class="muted"><small>Refunds belong to the day and cashier that processed them. Categories use the label recorded when sold. The Excel report includes Summary, Days, Items, Category, and Cashier sheets.</small></p>`;
}
async function renderShifts(){
  const pageSize=10;
  const [openData,historyData]=await Promise.all([api('/shifts?status=open'),api(`/shifts?status=closed&page=${shiftHistoryPage}&page_size=${pageSize}`)]);
  const openShifts=openData.shifts,closedShifts=historyData.shifts,total=historyData.total;
  const pageCount=Math.max(1,Math.ceil(total/pageSize));
  if(shiftHistoryPage>pageCount){shiftHistoryPage=pageCount;return renderShifts();}
  S.shiftRows=openShifts;
  const shiftTable=rows=>table(['Cashier','Shift','Day','Opening cash','Expected','Counted','Variance','Status',''],rows.map(s=>`<tr><td><strong>${e(s.display_name)}</strong></td><td>#${s.shift_id}</td><td>Day ${s.day_number}</td><td>${money(s.opening_cash_minor)}</td><td>${money(s.live_expected_minor)}</td><td>${s.counted_cash_minor===null?'—':money(s.counted_cash_minor)}</td><td>${s.variance_minor===null?'—':money(s.variance_minor)}</td><td>${pill(s.status,s.status==='open'?'success':s.variance_minor?'warn':'')}</td><td>${s.status==='open'&&managerAccess()?button('Manager close','manager-close-shift','light','shield',`data-id="${s.shift_id}"`):''}</td></tr>`));
  const first=(shiftHistoryPage-1)*pageSize;
  const pager=total?`<nav class="shift-pager" aria-label="Shift history pages">${button('Previous','shift-page','light','','data-step="-1" '+(shiftHistoryPage===1?'disabled':''))}<span>Page ${shiftHistoryPage} of ${pageCount} · ${first+1}–${first+closedShifts.length} of ${total}</span>${button('Next','shift-page','light','','data-step="1" '+(shiftHistoryPage===pageCount?'disabled':''))}</nav>`:'';
  $('#page').innerHTML=heading('A balanced counter.','Open shifts and a paged history of closed shifts.',S.shift?button('Close my shift','close-shift','green','clock'):button('Open my shift','open-shift','green','plus',!S.day?'disabled':''))+`<div class="panel"><div class="panel-title"><h2>Open cashier shifts</h2><span class="muted">${openShifts.length} open${managerAccess()?' · managers can close each shift':''}</span></div>${openShifts.length?shiftTable(openShifts):'<p class="shift-no-open">No open shifts right now.</p>'}</div><div class="panel"><div class="panel-title"><h2>Shift history</h2><span class="muted">${total} closed shifts</span></div>${closedShifts.length?shiftTable(closedShifts)+pager:empty('No closed shifts yet','Completed shifts appear here.')}</div>`;
}
function askShiftCloseConfirmation(shift,counted,reason='',order=null){
  return new Promise(resolve=>{
    const original=$('#modal-root .modal-overlay'),overlay=document.createElement('div');
    overlay.className='modal-overlay shift-confirm-overlay';
    overlay.innerHTML=`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="shift-confirm-title"><div class="modal-head"><h2 id="shift-confirm-title">Check the cash amount before closing</h2><button type="button" class="icon-btn" aria-label="Back to shift form" data-shift-confirm="back">${icon('close')}</button></div><div class="modal-body"><p class="payment-confirm-ticket">${e(shift.display_name)} · shift #${shift.shift_id}</p><dl class="payment-confirm-summary"><div><dt>Expected cash</dt><dd>${money(shift.live_expected_minor)}</dd></div><div><dt>Actual cash entered</dt><dd>${money(counted)}</dd></div><div><dt>Difference</dt><dd>${money(counted-shift.live_expected_minor)}</dd></div></dl>${reason?`<p class="shift-confirm-detail">Reason: ${e(reason)}</p>`:''}${order?`<p class="shift-confirm-detail">Unpaid order ${e(order.ticket_number)} will be canceled.</p>`:''}<label class="check-field shift-confirm-check"><input type="checkbox" id="shift-amount-checked">I checked the entered amount against the cash in the drawer.</label><div class="modal-actions"><button type="button" class="btn light" data-shift-confirm="back">Back to edit</button><button type="button" class="btn green" data-shift-confirm="yes" disabled>Confirm close shift${icon('check')}</button></div></div></section>`;
    original.hidden=true;$('#modal-root').appendChild(overlay);
    const checked=$('#shift-amount-checked',overlay),confirm=$('[data-shift-confirm=yes]',overlay);
    checked.addEventListener('change',()=>{confirm.disabled=!checked.checked;});
    let settled=false;
    const finish=approved=>{
      if(settled)return;settled=true;shiftConfirmationCancel=null;overlay.remove();original.hidden=false;
      if(!approved&&original.isConnected)$('[name=counted_cash]',original)?.focus({preventScroll:true});
      resolve(approved);
    };
    shiftConfirmationCancel=()=>finish(false);
    overlay.addEventListener('click',ev=>{const choice=ev.target.closest('[data-shift-confirm]');if(choice&&!choice.disabled)finish(choice.dataset.shiftConfirm==='yes');});
    checked.focus({preventScroll:true});
  });
}
function managerCloseShift(sid){
  const s=S.shiftRows.find(s=>s.shift_id===sid),order=s.open_ticket;
  const reasons=[['','Select a reason'],['End of shift','End of shift'],['Cashier unavailable','Cashier unavailable'],['Cashier forgot to close shift','Cashier forgot to close shift'],['Manager counted the drawer','Manager counted the drawer'],['Shift opened by mistake','Shift opened by mistake'],['Other','Other — enter details']];
  formModal('Close cashier shift',`<div class="shift-expected field full"><span class="shift-expected-context">${e(s.display_name)} · shift #${s.shift_id}</span><span class="shift-expected-label">Expected cash in drawer</span><strong>${money(s.live_expected_minor)}</strong><small>Verify the payment outcome and actual drawer count before closing.</small></div>`+(order?`<div class="field full"><strong>Open unpaid order ${e(order.ticket_number)}</strong><small>${order.lines.map(l=>e(l.quantity+' × '+l.description)).join('<br>')||'Empty order'}</small><label class="check-field"><input type="checkbox" name="cancel_open_order" required>I reviewed this order and confirm its cancellation.</label></div>`:'')+field('Actual cash counted','counted_cash','text',s.live_expected_minor===0?'0.00':'','required inputmode="decimal"')+selectField('Reason for manager closure','reason_choice',reasons,'','required')+`<div class="field full"><small>${s.live_expected_minor===0?'No cash is expected. Check the drawer: leave 0.00 if it is empty, including when this shift was opened by mistake. Enter any cash you find.':'Count the cash in the drawer and enter the amount you find.'}</small></div><div class="field full" id="other-shift-reason" hidden><label for="f-other_reason">Other reason</label><input id="f-other_reason" name="other_reason" type="text" maxlength="300" placeholder="Explain why this shift is being closed"></div>`+approval(),async data=>{
    const counted=minor(data.counted_cash),reason=data.reason_choice==='Other'?data.other_reason.trim():data.reason_choice;
    requireClient(reason,'Select or enter a reason for manager closure.');
    if(!await askShiftCloseConfirmation(s,counted,reason,order))return;
    await api('/shifts/'+sid+'/close','POST',{manager_password:data.manager_password,reason,counted_cash_minor:counted,cancel_open_order:data.cancel_open_order==='on',purchase_ticket_id:order?.purchase_ticket_id||null,ticket_version:order?.version??null});
    closeModal();shiftHistoryPage=1;await refreshState();await navigate(S.page==='management'?'management':'shifts');toast('Shift closed with the manager approval recorded.');
  },'Review closure');
  const reasonSelect=$('#f-reason_choice'),otherField=$('#other-shift-reason'),otherInput=$('#f-other_reason');
  reasonSelect.addEventListener('change',()=>{const other=reasonSelect.value==='Other';otherField.hidden=!other;otherInput.required=other;if(!other)otherInput.value='';});
}
async function closeShift(){
  const {shifts}=await api('/shifts?status=open'),current=shifts.find(s=>s.shift_id===S.shift.shift_id);
  formModal('Count and close your shift',`<div class="shift-expected field full"><span class="shift-expected-label">Expected cash in drawer</span><strong>${money(current.live_expected_minor)}</strong></div>`+field('Actual cash counted','counted_cash','text',current.live_expected_minor===0?'0.00':'','required inputmode="decimal"')+`<div class="field full"><small>${current.live_expected_minor===0?'No cash is expected. Check the drawer: leave 0.00 if it is empty, or enter any cash you find.':'Count the cash in the drawer and enter the amount you find.'} Complete or cancel your open ticket first.</small></div>`,async data=>{
    const counted=minor(data.counted_cash);
    if(!await askShiftCloseConfirmation(current,counted))return;
    const result=await api('/shifts/close','POST',{counted_cash_minor:counted});
    closeModal();shiftHistoryPage=1;S.page=S.page==='management'?'management':'shifts';await boot();toast('Shift closed. Cash variance: '+money(result.variance_minor));
  },'Review closure');
}
function refundAmount(line,quantity){
  const previous=line.returned_quantity||0;
  return Math.floor((previous+quantity)*line.line_total_minor/line.quantity)-Math.floor(previous*line.line_total_minor/line.quantity);
}
async function returnSale(sid){
  const r=await api('/sales/'+sid),available=r.lines.filter(l=>l.quantity>l.returned_quantity);
  requireClient(available.length,'All items from this sale have already been returned or voided.');
  formModal('Return or void sale',`<div class="notice field full">${e(receiptNumber(r.sale.receipt_number))} · Refunds are paid from your current open shift.</div>`+selectField('Correction type','correction_type',[['return','Return selected items'],['void','Void the entire sale']])+`<div class="field full"><div class="refund-line"><strong>Item</strong><small>Return qty</small><small>Restock qty</small></div>${available.map(l=>`<div class="refund-line"><div>${e(l.description_snapshot)}<small>${l.quantity-l.returned_quantity} remaining · ${money(l.line_total_minor)} paid for ${l.quantity} sold</small><small id="refund-line-${l.sale_line_id}">Refund: ${money(0)}</small></div><input aria-label="Return quantity for ${e(l.description_snapshot)}" type="number" name="qty-${l.sale_line_id}" value="0" min="0" max="${l.quantity-l.returned_quantity}" step="1"><input aria-label="Restock quantity for ${e(l.description_snapshot)}" type="number" name="restock-${l.sale_line_id}" value="0" min="0" max="${l.quantity-l.returned_quantity}" step="1"></div>`).join('')}<small>Only restock sellable items. A void must include every sold item.</small></div><div class="change-line" role="status" aria-live="polite"><span>Refund to customer</span><strong id="refund-total">${money(0)}</strong></div><div class="field full"><small id="refund-help">Calculated from what the customer actually paid after any discount. Restock qty only changes inventory.</small></div>`+field('Reason','reason','text','','required')+approval(),async data=>{
    const form=$('#modal-form');form.dataset.requestKey ||= key();
    const lines=available.filter(l=>Number(data['qty-'+l.sale_line_id])>0).map(l=>({sale_line_id:l.sale_line_id,quantity:Number(data['qty-'+l.sale_line_id]),restock_quantity:Number(data['restock-'+l.sale_line_id])}));
    const result=await api('/sales/'+sid+'/corrections','POST',{...data,request_key:form.dataset.requestKey,lines});
    closeModal();await loadCatalog();await showReceipt(sid);toast('Correction recorded'+(result.refund_minor?': '+money(result.refund_minor)+' refunded.':'.'));
  },'Record correction',true);
  const form=$('#modal-form');
  const updateRefund=()=>{
    let total=0,valid=true;
    for(const line of available){
      const quantity=Number($(`[name="qty-${line.sale_line_id}"]`,form).value),lineValid=Number.isSafeInteger(quantity)&&quantity>=0&&quantity<=line.quantity-line.returned_quantity;
      $(`#refund-line-${line.sale_line_id}`,form).textContent=lineValid?'Refund: '+money(refundAmount(line,quantity)):'Enter a valid return quantity.';
      if(lineValid)total+=refundAmount(line,quantity);else valid=false;
    }
    $('#refund-total',form).textContent=valid?money(total):'—';
    $('#refund-help',form).textContent=valid?'Calculated from what the customer actually paid after any discount. Restock qty only changes inventory.':'Enter whole return quantities within the remaining sold amounts.';
  };
  form.addEventListener('input',updateRefund);form.addEventListener('change',updateRefund);updateRefund();
}
async function renderTeam(){const {users}=await api('/team');S.team=users;$('#page').innerHTML=heading('A counter with your people.','Each action stays connected to the account that performed it.',button('Add account','new-user','green','plus'))+`<div class="panel"><div class="panel-title"><h2>Accounts</h2><span class="muted">Passwords are never displayed</span></div>${table(['Person','Username','Role','Status',''],users.map(u=>`<tr><td><strong>${e(u.display_name)}</strong></td><td class="mono">${e(u.username)}</td><td>${e(roleLabel(u))}</td><td>${pill(u.active?'Active':'Disabled',u.active?'success':'warn')}</td><td>${u.role==='it_admin'&&u.user_id!==S.user.user_id?'<span class="muted" title="Only ginflorita can update this account">Locked</span>':button('Manage','edit-user','light','edit',`data-id="${u.user_id}"`)}</td></tr>`))}</div>`;}
function userForm(uid){
  const u=S.team?.find(u=>u.user_id===uid),locked=u?.role==='it_admin';
  if(locked&&uid!==S.user.user_id)return toast('Only ginflorita can update this account.',true);
  const roleField=locked?'<div class="field"><label>Role</label><span>IT System Administrator (locked)</span><input type="hidden" name="role" value="it_admin"></div>':selectField('Role','role',[['cashier','Cashier'],['manager','Manager']],u?.role||'cashier');
  const statusField=locked?'<div class="field"><label>Status</label><span>Active (locked)</span><input type="hidden" name="active" value="true"></div>':selectField('Status','active',[['true','Active'],['false','Disabled']],String(u?!!u.active:true));
  formModal(u?'Manage account':'Create an account',field('Display name','display_name','text',u?.display_name||'','required')+(u?`<div class="field"><label>Username</label><input value="${e(u.username)}" disabled></div>`:field('Username','username','text','','required minlength="3" maxlength="50"'))+roleField+statusField+`<div class="field full"><label for="f-password">${u?'New password (leave blank to keep current)':'Password'}</label><input type="password" name="password" id="f-password" autocomplete="new-password" minlength="12" ${u?'':'required'}></div>${locked?'<div class="field full"><small>Only ginflorita can update this account. Its role and active status are locked.</small></div>':''}`+approval(),async data=>{await api(u?'/users/'+uid:'/users',u?'PUT':'POST',{...data,active:data.active==='true'});closeModal();await renderTeam();toast('Account saved.');},'Save account');
}
function auditActionLabel(action){return ({'shift.closed_by_manager':'Manager closed shift','shift.closed':'Cashier closed shift'})[action]||action.replace(/[._]/g,' ').replace(/^./,c=>c.toUpperCase());}
function auditRecordLabel(a){if(a.entity_type==='shifts')return `Shift #${a.entity_key}`;if(a.entity_type==='bazaars')return `Event #${a.entity_key}`;if(a.entity_type==='bazaar_days')return `Business day #${a.entity_key}`;return `${a.entity_type.replaceAll('_',' ')} ${a.entity_key||''}`.trim();}
function auditSnapshot(raw){try{return raw?JSON.parse(raw):null;}catch{return raw;}}
function auditTechnicalDetails(a){
  const before=auditSnapshot(a.before_json),after=auditSnapshot(a.after_json);
  if(before===null&&after===null)return '';
  return `<details class="audit-technical"><summary>Technical record</summary>${before!==null?`<strong>Before</strong><pre>${e(JSON.stringify(before,null,2))}</pre>`:''}${after!==null?`<strong>After</strong><pre>${e(JSON.stringify(after,null,2))}</pre>`:''}</details>`;
}
function auditDetails(a){
  const after=auditSnapshot(a.after_json),shiftClose=a.entity_type==='shifts'&&['shift.closed','shift.closed_by_manager'].includes(a.action);
  const fact=(label,value)=>`<div><dt>${e(label)}</dt><dd>${e(value)}</dd></div>`;
  if(shiftClose&&after&&typeof after==='object'){
    const cashier=a.subject_display_name||(after.cashier_user_id?`User #${after.cashier_user_id}`:'Unknown cashier');
    const facts=fact('Cashier',cashier)+fact('Closed by',a.display_name||'System')+fact('Time',timestamp(a.created_at))+(a.reason?fact('Reason',a.reason):'')+
      (Number.isInteger(after.expected_minor)?fact('Expected cash',money(after.expected_minor)):'')+
      (Number.isInteger(after.counted_minor)?fact('Cash counted',money(after.counted_minor)):'')+
      (Number.isInteger(after.variance_minor)?fact('Difference',money(after.variance_minor)):'');
    modal(`Shift #${a.entity_key} closed`,`<div class="stack"><p>${e(auditActionLabel(a.action))}</p><dl class="audit-facts">${facts}</dl>${auditTechnicalDetails(a)}</div>`);
    return;
  }
  const facts=fact('Action',auditActionLabel(a.action))+fact('Record',auditRecordLabel(a))+fact('Person',a.display_name||a.attempted_username||'System')+fact('Time',timestamp(a.created_at))+(a.reason?fact('Reason',a.reason):'');
  modal('Audit event #'+a.audit_event_id,`<div class="stack"><dl class="audit-facts">${facts}</dl>${auditTechnicalDetails(a)}</div>`);
}
async function renderAudit(){const {events}=await api('/audit'+(auditEventId?'?event_id='+auditEventId:''));$('#page').innerHTML=heading(auditEventId?'Archived audit: '+archiveEventName:'The details stay with you.','An append-only record of who did what, and when.',(auditEventId?button('Current event','current-audit','light','refresh'):'')+button('Refresh','refresh-page','light','refresh'))+`<div class="panel"><div class="panel-title"><h2>Audit trail</h2><span class="muted">Latest 500 events</span></div>${events.length?table(['Time','Person','Action','Record','Reason / details'],events.map(a=>`<tr><td>${e(timestamp(a.created_at))}</td><td>${e(a.display_name||a.attempted_username||'System')}</td><td>${e(auditActionLabel(a.action))}</td><td>${e(auditRecordLabel(a))}</td><td class="audit-reason">${e(a.reason||'—')}${a.after_json?`<br>${button('Details','audit-details','light small','',`data-id="${a.audit_event_id}"`)}`:''}</td></tr>`)):empty('A record from the start','Activity will appear here as your team uses the counter.')}</div>`;S.auditEvents=events;}
async function renderManagement(){
  let card;
  if(S.day){
    const {shifts}=await api('/shifts?status=open');
    const unpaid=shifts.filter(shift=>shift.open_ticket).length;
    const dayNumber=S.day.day_number;
    if(shifts.length){
      const shiftText=`${shifts.length} ${shifts.length===1?'cashier shift is':'cashier shifts are'} still open.`;
      const orderText=unpaid?` ${unpaid} unpaid ${unpaid===1?'order needs':'orders need'} to be completed or cancelled.`:'';
      card=`<div class="eyebrow">Day ${dayNumber} · ${e(S.day.business_date)}</div><h2>Close cashier shifts first</h2><p>${shiftText}${orderText} Count each drawer and close its shift in Cashier shifts.</p><p class="business-day-note">You can close Day ${dayNumber} here when every shift is closed.</p><button type="button" class="btn green" data-page="shifts">${icon('clock')}Review cashier shifts</button>`;
    }else{
      card=`<div class="eyebrow">Day ${dayNumber} · ${e(S.day.business_date)}</div><h2>Ready to close Day ${dayNumber}</h2><p>All cashier shifts are closed. Close the day to save its final totals and create a backup.</p>${button(`Close Day ${dayNumber}`,'close-day','green','sun')}`;
    }
  }else if(!S.bazaar){
    card=`<h2>Waiting for the next event</h2><p>The IT System Administrator starts the event. After that, a manager can open Day 1 here.</p>${S.user.role==='it_admin'?button('Open Events','go-to-events','green','sun'):''}`;
  }else{
    card=`<h2>Start the next business day</h2><p>Choose the business date and enter your manager password. Cashiers can then open their shifts in Checkout.</p>${button('Open day','open-day','green','sun')}`;
  }
  $('#page').innerHTML=heading('Business day','Open and close each business day here.')+`<section class="panel business-day-card" aria-label="Next business day action"><div class="panel-body">${card}</div></section>`;
}
async function renderEvents(){
  const {events}=await api('/events');
  const current=events.find(item=>item.status==='active'),last=events[0];
  let action;
  if(current){
    action=`<h2>${e(current.event_name)}</h2><p>Started ${e(current.starts_on)}. Managers open and close business days; cashiers open and close their own shifts.</p>${button('Rename event','rename-event','light small','edit',`data-name="${e(current.event_name)}"`)}${S.day?`<p>Day ${S.day.day_number} is still open. Ask the manager to close it before ending this event.</p>`:button('End event','end-event','green','sun')}`;
  }else if(last&&!last.archive_backup){
    action=`<h2>Finish the archive</h2><p>The last event is closed, but its verified backup did not finish. Retry the archive before starting another event.</p>${button('Retry archive','retry-event-archive','green','download')}`;
  }else{
    action=`<h2>Ready for a new event</h2><p>Starting an event keeps products, accounts, and settings. Stock starts at zero; a manager can then open Day 1.</p>${button('Start event','start-event','green','plus')}`;
  }
  const archived=events.filter(item=>item.status==='closed');
  const rows=archived.map(item=>`<tr><td><strong>${e(item.event_name)}</strong></td><td>${e(item.starts_on)}${item.ends_on?' – '+e(item.ends_on):''}</td><td>${pill(item.archive_backup?'Archived':'Backup needed',item.archive_backup?'success':'warn')}</td><td class="event-actions">${button('View report','event-report','light small','chart',`data-id="${item.bazaar_id}" data-name="${e(item.event_name)}"`)}${button('Inventory','event-inventory','light small','box',`data-id="${item.bazaar_id}" data-name="${e(item.event_name)}"`)}${button('View audit','event-audit','light small','shield',`data-id="${item.bazaar_id}" data-name="${e(item.event_name)}"`)}<a class="btn light small" href="/api/reports?event_id=${item.bazaar_id}&format=xlsx">${icon('download')}Excel</a></td></tr>`);
  $('#page').innerHTML=heading('Events','The IT System Administrator starts and ends events. Each event keeps its own days, stock movements, sales, reports, and audit trail.')+`<section class="panel event-card"><div class="panel-body">${action}</div></section><section class="panel event-history"><div class="panel-title"><h2>Past events</h2><span class="muted">Read-only records</span></div>${rows.length?table(['Event','Dates','Archive','Reports and logs'],rows):empty('No past events yet','The finished event will appear here after it ends.')}</section>`;
}
function startEventModal(){
  formModal('Start a new event',`<div class="field full"><small>Products and current prices stay. Stock starts at zero, and a manager opens Day 1 after this event starts.</small></div>`+field('Event name','event_name','text','','required maxlength="120"')+approval(),async data=>{await api('/events/start','POST',data);closeModal();reportEventId=null;auditEventId=null;S.page='events';await boot();toast('New event started. Ask a manager to open Day 1.');},'Start event');
}
function renameEventModal(name){
  formModal('Name this event',field('Event name','event_name','text',name,'required maxlength="120"')+approval(),async data=>{await api('/events/rename','POST',data);closeModal();await renderEvents();toast('Event name saved.');},'Save name');
}
function endEventModal(){
  formModal('End this event',`<div class="field full"><small>All days, shifts, unpaid orders, and pending receipt print jobs must be finished. A verified backup will archive this event. The next event begins with zero stock while products stay in the catalog.</small></div><div class="field full"><label class="check-field"><input type="checkbox" name="checked" required><span>I checked the final reports and cash reconciliation.</span></label></div>`+approval(),async data=>{try{await api('/events/end','POST',data);}catch(error){await boot();throw error;}closeModal();S.page='events';await boot();toast('Event ended and archived.');},'End event');
}
function retryEventArchiveModal(){
  formModal('Retry event archive',`<div class="field full"><small>The completed event stays closed. A verified backup is required before starting another event.</small></div>`+approval(),async data=>{await api('/events/archive','POST',data);closeModal();S.page='events';await boot();toast('Event archive verified.');},'Retry archive');
}
async function renderDiscounts(){
  const config=await api('/discount');
  $('#page').innerHTML=heading('Checkout discounts','Set the rates cashiers can choose for an order.')+discountSettingsPanel(config);
}
const BACKUP_PAGE_SIZE=8;
async function renderBackups(){
  const data=await api('/backups'),runs=data.backups||[];
  const pageCount=Math.max(1,Math.ceil(runs.length/BACKUP_PAGE_SIZE));
  backupPage=Math.max(0,Math.min(backupPage,pageCount-1));
  const first=backupPage*BACKUP_PAGE_SIZE;
  const visible=runs.slice(first,first+BACKUP_PAGE_SIZE);
  const rows=visible.map(b=>`<tr><td>${e(timestamp(b.started_at))}</td><td>${pill(b.status,b.status==='verified'?'success':'error')}</td><td class="backup-file" title="${e(b.error_message||b.destination||'')}">${e(b.error_message||(b.destination||'').split(/[\\/]/).pop()||'—')}</td></tr>`);
  const pager=runs.length>BACKUP_PAGE_SIZE?`<nav class="backup-pager" aria-label="Backup history pages">${button('Previous','backup-page','light','','data-step="-1" '+(backupPage===0?'disabled':''))}<span>Page ${backupPage+1} of ${pageCount} · ${first+1}–${Math.min(first+BACKUP_PAGE_SIZE,runs.length)} of ${runs.length}</span>${button('Next','backup-page','light','','data-step="1" '+(backupPage===pageCount-1?'disabled':''))}</nav>`:'';
  $('#page').innerHTML=heading('Backups','Verified recovery copies for this POS.',button('Back up now','backup','green','download'))+`<div class="panel backup-overview"><div class="panel-body"><div><strong>Automatic backups</strong><p>Every 15 minutes while the server is running, at day close, and on request. Keep a copy on another drive.</p></div><div><strong>Backup folder</strong><p class="mono">${e(data.directory)}</p></div><div><strong>Restore</strong><p>Stop the server and follow docs/operations.md. Restore into a new folder, then verify before switching.</p></div></div></div><div class="panel backup-runs"><div class="panel-title"><h2>Recent backup runs</h2><span class="muted">Latest ${runs.length} · no automatic deletion</span></div>${runs.length?table(['Started','Result','File / issue'],rows)+pager:empty('Your first recovery copy','Create a backup after adding your catalog.','backup','Create backup')}</div>`;
}
async function renderPrinter(){
  const data=await api('/receipt-printer');
  $('#page').innerHTML=heading('Receipt printer','Set up printing for this laptop.')+printerSettingsPanel(data);
}
function managerAction(title,description,path){
  formModal(title,`<div class="field full"><small>${e(description)}</small></div>`+approval(),async data=>{
    const closingDay=S.day?.day_number;
    const result=await api(path,'POST',data);
    closeModal();
    S.page=path==='/backups'?'backups':path==='/days/close'?'management':'checkout';
    if(path==='/backups')backupPage=0;
    await boot();
    toast(result.backup?.status==='failed'?'Day closed, but backup failed. Check Backups.':path==='/backups'?'Backup verified.':path==='/days/close'?`Day ${closingDay} closed. Open the next day here.`:'Operation completed.',result.backup?.status==='failed');
  },title);
}

document.addEventListener('click',async ev=>{
  const target=ev.target.closest('button,[data-page]');if(!target)return;
  try{
    if(target.dataset.page){if(S.paying)return;await cartQueue;if(target.dataset.page==='checkout')return requestCheckout();if(target.dataset.page==='reports')reportEventId=null;if(target.dataset.page==='audit')auditEventId=null;if(target.dataset.page==='inventory')inventoryEventId=null;return await navigate(target.dataset.page);}
    if(target.dataset.productPage){S.productPage+=target.dataset.productPage==='next'?1:-1;renderProducts();$('#product-grid').scrollTop=0;return;}
    if(target.dataset.add){await productQuantityModal(Number(target.dataset.add));return;}
    if(target.dataset.qty){try{await addProduct(Number(target.dataset.qty),Number(target.dataset.delta));}finally{$('#product-search')?.focus({preventScroll:true});}return;}
    if(target.dataset.cash){$('#amount-paid').value=(Number(target.dataset.cash)/100).toFixed(2);$('#amount-paid').dispatchEvent(new Event('input'));return;}
    const action=target.dataset.action;if(!action)return;
    const id=Number(target.dataset.id);
    const actions={
      'checkout-fullscreen':openCheckoutFullscreen,'toggle-checkout-fullscreen':()=>checkoutFullscreen?leaveCheckoutFullscreen():enterCheckoutFullscreen(),'toggle-management':toggleManagement,
      'close-modal':closeModal,'boot':boot,'open-day':openDay,'open-shift':openShift,'close-shift':closeShift,'day-steps':async()=>{if(S.paying)return;await cartQueue;return navigate('management');},'pay':paymentModal,
      'go-to-events':()=>{closeModal();return navigate('events');},
      'start-event':startEventModal,'rename-event':()=>renameEventModal(target.dataset.name),'end-event':endEventModal,'retry-event-archive':retryEventArchiveModal,
      'event-report':()=>{reportEventId=id;archiveEventName=target.dataset.name;S.filters={};return navigate('reports');},
      'event-inventory':()=>{inventoryEventId=id;archiveEventName=target.dataset.name;Object.assign(inventoryFilters,{q:'',category_id:'',from:'',to:'',view:'products',product_page:1,movement_page:1});return navigate('inventory');},
      'event-audit':()=>{auditEventId=id;archiveEventName=target.dataset.name;return navigate('audit');},
      'current-report':()=>{reportEventId=null;S.filters={};return renderReports();},
      'current-inventory':()=>{inventoryEventId=null;return renderInventory();},
      'current-audit':()=>{auditEventId=null;return renderAudit();},
      'cancel-ticket':cancelTicket,'transfer-ticket':transferTicket,'set-cart-quantity':()=>setCartQuantityModal(id),'new-product':()=>productForm(),'edit-product':()=>productForm(id),'bulk-upload-products':productImportForm,'save-product-import':()=>savePendingProductImport(target),'complete-product':()=>productForm(undefined,id),'new-stock':stockForm,
      'new-user':()=>userForm(),'edit-user':()=>userForm(id),'manager-close-shift':()=>managerCloseShift(id),
      'view-product-image':()=>viewProductImage(id),'view-cart-description':()=>viewCartDescription(id),'view-receipt':()=>showReceipt(id),'return-sale':()=>returnSale(id),
      'refresh-page':()=>navigate(S.page),'backup-page':()=>{backupPage+=Number(target.dataset.step);return renderBackups();},
      'catalog-page':async()=>{const kind=target.dataset.kind;if(kind==='drafts')catalogDraftPage=Math.max(1,catalogDraftPage+Number(target.dataset.step));else catalogProductPage=Math.max(1,catalogProductPage+Number(target.dataset.step));await renderCatalog(false);$(kind==='drafts'?'.catalog-drafts':'.catalog-products')?.scrollIntoView({block:'start'});},
      'catalog-clear-search':()=>{catalogSearch='';catalogDraftPage=1;catalogProductPage=1;return renderCatalog(false);},
      'transaction-page':async()=>{transactionPage=Math.max(1,transactionPage+Number(target.dataset.step));await renderTransactions();$('.transaction-panel')?.scrollIntoView({block:'start'});},
      'inventory-view':()=>{inventoryFilters.view=target.dataset.view;return renderInventory();},
      'inventory-page':()=>{const key=target.dataset.kind==='product'?'product_page':'movement_page';inventoryFilters[key]=Math.max(1,inventoryFilters[key]+Number(target.dataset.step));return renderInventory();},
      'inventory-clear':()=>{Object.assign(inventoryFilters,{q:'',category_id:'',from:'',to:'',product_page:1,movement_page:1});return renderInventory();},
      'inventory-category':()=>{inventoryFilters.category_id=String(id);inventoryFilters.product_page=1;inventoryFilters.movement_page=1;inventoryFilters.view='products';return renderInventory();},
      'shift-page':()=>{shiftHistoryPage=Math.max(1,shiftHistoryPage+Number(target.dataset.step));return renderShifts();},
      'clear-filters':async()=>{S.filters={};if(S.page==='transactions'){transactionSearch='';transactionPage=1;}await navigate(S.page);},
      'logout':confirmLogout,
      'confirm-logout':async()=>{target.disabled=true;try{await signOut();}catch(error){target.disabled=false;throw error;}},
      'new-category':()=>formModal('Add a category',field('Category name','name','text','','required'),async data=>{await api('/categories','POST',data);closeModal();await renderCatalog();toast('Category added.');},'Add category'),
      'close-day':()=>managerAction(`Close Day ${S.day?.day_number||''}`,'All cashier shifts and unpaid orders must be closed. The POS will create a backup, then you can open the next day here.','/days/close'),
      'backup':()=>managerAction('Create backup','Create and verify a snapshot of the live database, including product images.','/backups'),
      'add-discount':discountForm,'delete-discount':()=>deleteDiscount(id),
      'pair-printer':pairPrinter,'configure-printer':configurePrinter,'disconnect-printer':disconnectPrinter,'refresh-printers':renderPrinter,'start-print-helper':startPrintHelper,'resolve-print':()=>resolvePrint(id),'printer-copy':()=>queuePrinterCopy(id),
      'print-receipt':async()=>{
        target.disabled=true;
        try{
          await api('/sales/'+id+'/reprint','POST',{});
          await showReceipt(id);
          const previousTitle=document.title;
          document.title=receiptNumber(currentReceipt.sale.receipt_number);
          const restoreTitle=()=>{document.title=previousTitle;};
          window.addEventListener('afterprint',restoreTitle,{once:true});
          try{window.print();}catch(error){window.removeEventListener('afterprint',restoreTitle);restoreTitle();throw error;}
        }finally{target.disabled=false;}
      },
      'audit-details':()=>{const a=S.auditEvents.find(a=>a.audit_event_id===id);if(a)auditDetails(a);}
    };
    if(actions[action])await actions[action]();
  }catch(error){toast(error.message,true);}
});
document.addEventListener('change',async ev=>{
  if(ev.target.id==='checkout-category'){
    S.category=ev.target.value;S.productPage=0;renderProducts();
    $('#product-grid')?.scrollTo({top:0});$('#product-search')?.focus({preventScroll:true});
    return;
  }
  if(ev.target.id==='discount-choice'){
    const percent=Number(ev.target.value);
    try{
      await cartQueue;
      requireClient(S.ticket&&!S.cartError,'Refresh the order before choosing a discount.');
      requireClient(!localStorage.getItem(`bazaar-pending-${S.user.user_id}-${S.ticket.purchase_ticket_id}`),'Review the previous payment result before changing this order.');
      S.ticket=await api('/tickets/'+S.ticket.purchase_ticket_id+'/discount','PUT',{version:S.ticket.version,discount_percent_bp:percent});
      renderCart();
    }catch(error){
      if(error.status===409&&S.ticket)try{S.ticket=await api('/tickets/'+S.ticket.purchase_ticket_id);}catch{}
      renderCart();toast(error.message,true);
    }
    return;
  }
  if(ev.target.dataset.filter){S.filters[ev.target.dataset.filter]=ev.target.value;if(S.page==='transactions')transactionPage=1;await navigate(S.page);}
});
document.addEventListener('keydown',ev=>{if(ev.key==='Escape'){if($('.modal'))closeModal();else if(checkoutFullscreen)void leaveCheckoutFullscreen();}if(ev.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){ev.preventDefault();$('#product-search')?.focus();}if(ev.key==='Tab'&&$('.modal')){const focusables=$$('button:not(:disabled),input:not(:disabled),select,textarea,a[href]',$$('.modal').at(-1));const first=focusables[0],last=focusables.at(-1);if(ev.shiftKey&&document.activeElement===first){ev.preventDefault();last.focus();}else if(!ev.shiftKey&&document.activeElement===last){ev.preventDefault();first.focus();}}});
setInterval(async()=>{if(pollBusy||S.paying||document.hidden)return;pollBusy=true;try{const old=JSON.stringify([S.user?.user_id,S.day?.bazaar_day_id,S.shift?.shift_id]);const result=await refreshState();const next=JSON.stringify([result.user?.user_id,result.day?.bazaar_day_id,result.shift?.shift_id]);if(old!==next&&!$('.modal'))await boot();}catch{}finally{pollBusy=false;}},20000);
setInterval(refreshCheckoutStock,30000);
boot();

function discountSettingsPanel(config){
  const rates=config.rates||[];
  return `<div class="panel discount-panel"><div class="panel-title"><h2>Available rates</h2>${button('Add rate','add-discount','green','plus')}</div><div class="discount-list">${rates.length?rates.map(rate=>`<div class="discount-rate-row"><strong>${percentLabel(rate.percent_bp)}</strong>${button('Delete','delete-discount','light small','close',`data-id="${rate.discount_rate_id}"`)}</div>`).join(''):'<p class="muted">No rates yet. Add a percentage for cashiers to choose.</p>'}</div><p class="list-note">Removing a rate clears it from open orders. Completed receipts keep the rate already charged.</p></div>`;
}
async function discountForm(){
  formModal('Add checkout discount',field('Discount percentage','percentage','number','','required min="0.01" max="99" step="0.01"')+`<div class="field full"><small>Add a rate from 0.01% to 99%. Cashiers will see it in the order discount list.</small></div>`+approval(),async data=>{
    const value=String(data.percentage).trim();
    requireClient(/^\d{1,2}(\.\d{1,2})?$/.test(value)&&Number(value)>0&&Number(value)<=99,'Enter a percentage from 0.01 to 99, with up to two decimal places.');
    await api('/discount','POST',{discount_percent_bp:Math.round(Number(value)*100),manager_password:data.manager_password});
    closeModal();await renderDiscounts();toast('Discount rate added.');
  },'Add rate');
}
async function deleteDiscount(id){
  const {rates}=await api('/discount'),rate=rates.find(item=>item.discount_rate_id===id);
  requireClient(rate,'This discount rate is no longer available. Refresh Discounts.');
  formModal('Delete '+percentLabel(rate.percent_bp)+' discount',`<div class="field full"><p>Cashiers will no longer be able to choose this rate. Open orders using it will return to no discount and must be reviewed before payment. Completed receipts keep the discount already charged.</p></div>`+approval(),async data=>{
    await api('/discount/'+id,'DELETE',{manager_password:data.manager_password});
    closeModal();await renderDiscounts();toast(percentLabel(rate.percent_bp)+' discount removed.');
  },'Delete rate');
}

function printerSettingsPanel(data){
  const p=data.printer;
  const paper=p?.paper_size==='letter'?'Letter':p?.paper_size==='roll_58'?'58 mm':'80 mm';
  const status=p?.enabled?(p.online?'Ready to print':'Printer offline'):p?'Automatic printing off':'Not paired';
  const pending=data.jobs.filter(j=>['queued','claimed'].includes(j.status));
  const history=data.jobs.filter(j=>['submitted','failed'].includes(j.status));
  const jobTable=jobs=>table(['Receipt','Printer','Status',''],jobs.map(j=>`<tr><td>${e(receiptNumber(j.receipt_number))}</td><td>${e(j.printer_name)}</td><td>${e(j.status)}${j.error_message?'<br><small>'+e(j.error_message)+'</small>':''}</td><td>${['queued','claimed'].includes(j.status)?button('Review / close','resolve-print','light','',`data-id="${j.receipt_print_job_id}"`):''}</td></tr>`));
  return `<div class="panel printer-settings"><div class="panel-title"><h2>Receipt printer · this laptop</h2>${pill(status,p?.enabled&&p.online?'success':'warn')}</div><div class="panel-body"><div class="setting-row"><div><h3>${e(p?.printer_name||'No receipt printer selected')}</h3><p>${p?(p.online?'Print helper connected':'Print helper offline'):'No print helper paired'}${p?.enabled?' · '+paper:''}<br>${p?.enabled?'After Yes confirms payment, one receipt is queued automatically.':'Automatic printing is off. Browser Print / save PDF remains available.'}</p></div></div><div class="notice">Install the Windows printer driver, pair the helper, and choose the printer below. If the helper is offline, run Start-Print-Helper.cmd on this laptop. On the POS host, Connect printer can start a saved helper in the background.</div><div class="actions printer-actions">${button('Pair print helper','pair-printer','light','laptop')}${p?button('Choose printer','configure-printer','green','print'):''}${p&&!p.online&&canStartPrintHelper()?button('Connect printer','start-print-helper','light','print'):''}${p?button('Disconnect printer','disconnect-printer','light','close'):''}${button('Refresh status','refresh-printers','light','refresh')}</div>${pending.length?`<section class="printer-pending"><h3>Waiting or interrupted receipts</h3><p class="muted">A queued receipt waits for the helper. If printing was interrupted, check the printer and Windows queue before closing its record.</p>${jobTable(pending)}</section>`:''}<details class="printer-history"><summary>View recent print history${history.length?` (${history.length})`:''}</summary><p class="muted">Submitted means Windows accepted the job. Failed records remain here even after the printing issue is fixed.</p>${history.length?jobTable(history):'<p class="muted">No completed printer jobs yet.</p>'}</details></div></div>`;
}
function disconnectPrinter(){
  formModal('Disconnect receipt printer',`<div class="field full"><p>Automatic receipt printing will stop on this laptop. The print helper pairing will be revoked.</p><p>Receipts waiting to print will be marked as not printed. Check each receipt before making another copy. A receipt already being sent to Windows must be reviewed and closed first.</p><p>To reconnect later, pair the helper again and choose a printer in Settings.</p></div>`,async()=>{
    const result=await api('/receipt-printer','DELETE',{});
    closeModal();S.receiptPrinter=null;await renderPrinter();
    toast(result.cancelled_jobs?`Printer disconnected. ${result.cancelled_jobs} waiting receipt(s) need review.`:'Printer disconnected from this laptop.');
  },'Disconnect printer');
}
async function pairPrinter(){
  formModal('Pair this laptop’s print helper',`<div class="field full"><p>Double-click Pair-Print-Helper.cmd on this laptop. Enter the POS address and the pairing code shown next.</p><p>Replacing a pairing disables automatic printing until you choose a printer again.</p></div>`,async()=>{
    const r=await api('/receipt-printer/pair','POST',{});
    modal('Print helper pairing code',`<p>Shown once. Double-click Pair-Print-Helper.cmd on this laptop and enter this code. If an old helper is still closing, wait a few seconds and try again.</p><div class="field"><label for="printer-pairing-code">Pairing code</label><input id="printer-pairing-code" readonly value="${e(r.pairing_token)}"></div><p>POS address: <strong>${e(location.origin)}</strong></p><p>For a LAN connection, enter the trusted POS certificate file when the helper asks. Keep the helper running, close this dialog, then click Refresh status and Choose printer.</p><div class="modal-actions">${button('Done','close-modal','green')}</div>`);
  },'Create pairing code');
}
async function configurePrinter(){
  const {printer:p}=await api('/receipt-printer');
  if(!p)throw new Error('Pair the print helper on this laptop first.');
  const names=[...new Set([p.printer_name,...p.available_printers])].filter(Boolean);
  formModal('Receipt printer for this laptop',`<div class="field full"><small>${p.online?'Print helper connected.':'Start the print helper, then refresh Settings to detect printers.'}</small></div>`+selectField('Printer','printer_name',[['','Choose a Windows printer'],...names.map(n=>[n,n])],p.printer_name)+selectField('Paper size','paper_size',[['letter','Letter · 8.5 × 11 in'],['roll_80','80 mm receipt roll'],['roll_58','58 mm receipt roll']],p.paper_size||('roll_'+p.paper_width_mm))+selectField('Automatic printing after payment','enabled',[['false','Off — manual browser printing'],['true','On — use this printer']],String(!!p.enabled)),async data=>{
    await api('/receipt-printer','PUT',{printer_name:data.printer_name,paper_size:data.paper_size,enabled:data.enabled==='true'});closeModal();await renderPrinter();toast('Printer settings saved for this laptop.');
  },'Save printer');
}
function resolvePrint(id){formModal('Review interrupted printing',`<div class="field full"><small>Check the printer and its Windows queue first. Closing this record cannot stop a job already being printed. Stop the helper and cancel any unwanted Windows job before making a copy.</small></div>`+field('What did you check?','reason','text','','required maxlength="300"'),async data=>{await api('/receipt-printer/jobs/'+id+'/resolve','POST',data);closeModal();await renderPrinter();},'Close pending record');}
async function queuePrinterCopy(sid){
  formModal('Print another receipt copy?',`<div class="field full"><p>Check the printer and Windows queue first. This creates another paper copy of the saved sale.</p></div>`,async()=>{await api('/sales/'+sid+'/printer-copy','POST',{});await showReceipt(sid);toast('Receipt copy queued.');},'Print copy');
}
async function refreshReceiptPrintStatus(sid){
  try{
    const data=await api('/receipt-printer?sale_id='+sid);if(currentReceipt?.sale.sale_id!==sid)return;
    let node=$('#receipt-print-status');
    if(!node){node=document.createElement('div');node.id='receipt-print-status';node.className='receipt-extra notice';$('.receipt')?.after(node);}
    const job=data.jobs.find(j=>j.sale_id===sid);
    node.innerHTML=job?`Receipt print: <strong>${e(job.status)}</strong> · ${e(job.printer_name)}<br>${e(job.error_message||({queued:data.printer?.online?'Waiting for printer helper.':'Start this laptop’s print helper to send the queued receipt.',claimed:'Sending or interrupted. Check the printer before making a copy.',submitted:'Sent to Windows printer queue. Check paper output.',failed:'Check the printer before making a copy.'}[job.status]))}`:'No automatic print record for this receipt on this laptop. Use Print / save PDF, or request a printer copy after checking for existing output.';
    if(data.printer?.enabled&&!['queued','claimed'].includes(job?.status)&&!$('[data-action=printer-copy]'))node.insertAdjacentHTML('beforeend',button('Print another copy','printer-copy','light','print',`data-id="${sid}"`));
    if(job&&['queued','claimed'].includes(job.status))setTimeout(()=>{if(currentReceipt?.sale.sale_id===sid)void refreshReceiptPrintStatus(sid);},2500);
  }catch{if(currentReceipt?.sale.sale_id===sid)toast('Sale saved. Printer status unavailable; check Transactions before printing a copy.',true);}
}
