"""Exercise Player wake-lock ownership with deterministic browser API responses."""
import pytest
from playwright.sync_api import expect

MOCK = """() => {
 const t=window.wakeTest={requests:0,releases:0,locks:[],deferred:false,fail:false,resolvers:[]};
 Object.defineProperty(navigator,'wakeLock',{configurable:true,value:{request:async type=>{
  if(type!=='screen')throw Error('Unexpected lock type');
  t.requests++;
  if(t.fail)throw Error('Power saving mode');
  if(t.deferred)await new Promise(resolve=>t.resolvers.push(resolve));
  const lock=new EventTarget();lock.released=false;
  lock.release=async()=>{if(lock.released)return;lock.released=true;t.releases++;lock.dispatchEvent(new Event('release'));};
  t.locks.push(lock);return lock;
 }}});
 window.setVisible=value=>{Object.defineProperty(document,'visibilityState',{configurable:true,value});document.dispatchEvent(new Event('visibilitychange'));};
}"""


def open_player(remote, page, remote_url, unsupported=None):
    extra = ("Object.defineProperty(window,'isSecureContext',{value:false});" if unsupported == 'insecure'
             else "delete Navigator.prototype.wakeLock; delete navigator.wakeLock;" if unsupported == 'missing_api' else '')
    page.add_init_script(f'({MOCK})();' + extra)
    page.route_web_socket('**/ws?role=tv', remote.websocket)
    page.goto(remote_url.replace('/remote', '/tv'))
    expect(page.locator('#song-title')).to_have_text('Current Song')


def counter(page, name, expected):
    page.wait_for_function('([name,n])=>window.wakeTest[name]===n', arg=[name, expected])


def test_player_activity_pause_visibility_and_error_only_queue(remote, page, remote_url):
    open_player(remote, page, remote_url)
    assert page.evaluate('wakeTest.requests') == 0  # Starts paused.
    remote.state['playing'] = True
    remote.push()
    counter(page, 'requests', 1)
    remote.push()
    expect(page.locator('#song-title')).to_have_text('Current Song')
    assert page.evaluate('wakeTest.requests') == 1
    remote.state['playing'] = False
    remote.push()
    counter(page, 'releases', 1)
    remote.state['playing'] = True
    remote.push()
    counter(page, 'requests', 2)
    page.evaluate("setVisible('hidden')")
    counter(page, 'releases', 2)
    page.evaluate("setVisible('visible')")
    counter(page, 'requests', 3)
    remote.state['current'] = None
    remote.state['upcoming'] = [{'key': 'preparing', 'id': 'aaaaaaaaaaa', 'title': 'Preparing', 'status': 'queued'}]
    remote.push()
    expect(page.locator('#on-deck li')).to_have_count(1)
    assert page.evaluate('wakeTest.releases') == 2
    remote.state['upcoming'][0]['status'] = 'error'
    remote.push()
    counter(page, 'releases', 3)
    remote.state['upcoming'] = []
    remote.push()
    page.evaluate("dispatchEvent(new Event('pagehide'))")
    assert page.evaluate('wakeTest.requests') == 3


def test_pending_request_is_released_if_paused_before_acquisition(remote, page, remote_url):
    open_player(remote, page, remote_url)
    page.evaluate('wakeTest.deferred=true')
    remote.state['playing'] = True
    remote.push()
    counter(page, 'requests', 1)
    remote.state['playing'] = False
    remote.push()
    expect(page.locator('#tv-play')).to_have_attribute('aria-label', 'Play')
    page.evaluate('wakeTest.resolvers.shift()()')
    counter(page, 'releases', 1)
    assert page.evaluate('wakeTest.requests') == 1


def test_rejection_auto_release_and_navigation_recover(remote, page, remote_url):
    open_player(remote, page, remote_url)
    page.clock.install()
    page.evaluate('wakeTest.fail=true')
    remote.state['playing'] = True
    remote.push()
    counter(page, 'requests', 1)
    remote.push()
    expect(page.locator('#tv-play')).to_have_attribute('aria-label', 'Pause')
    assert page.evaluate('wakeTest.requests') == 1  # Broadcasts do not bypass retry backoff.
    page.evaluate('wakeTest.fail=false')
    page.clock.run_for(5100)
    counter(page, 'requests', 2)
    page.wait_for_function('wakeTest.locks.length===1')
    page.evaluate('wakeTest.locks[0].release()')
    page.clock.run_for(5100)
    counter(page, 'requests', 3)
    page.wait_for_function('wakeTest.locks.length===2')
    page.evaluate("dispatchEvent(new Event('pagehide'))")
    counter(page, 'releases', 2)
    page.clock.run_for(6000)
    assert page.evaluate('wakeTest.requests') == 3
    page.evaluate("dispatchEvent(new Event('pageshow'))")
    counter(page, 'requests', 4)


@pytest.mark.parametrize('unsupported', ['insecure', 'missing_api'])
def test_player_without_supported_api_still_renders(remote, page, remote_url, unsupported):
    open_player(remote, page, remote_url, unsupported)
    remote.state['playing'] = True
    remote.push()
    expect(page.locator('#tv-play')).to_have_attribute('aria-label', 'Pause')
    assert page.evaluate('wakeTest.requests') == 0


def test_remote_does_not_request_screen_lock(remote, page, remote_url):
    page.add_init_script(f'({MOCK})();')
    remote.state['playing'] = True
    page.goto(remote_url)
    expect(page.locator('#connection-label')).to_have_text('Ready')
    assert page.evaluate('wakeTest.requests') == 0
