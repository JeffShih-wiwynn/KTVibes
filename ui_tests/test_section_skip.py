import pytest
from playwright.sync_api import expect


@pytest.mark.parametrize("theme", ["default", "classic"])
def test_section_button_lifecycle(remote, page, remote_url, theme):
    remote.state.update(theme=theme, position=0, sections={"intro": 15, "outro": 94})
    page.goto(remote_url)
    if theme == "classic":
        page.locator('[data-tab="queue"]').click()
    button = page.locator("#skip")
    expect(button).to_have_text("Skip intro")
    expect(button).to_be_enabled()
    button.click()
    remote.wait_command("skip_intro", key="current")
    remote.state.update(position=15, intro_pending=True)
    remote.push()
    expect(button).to_be_disabled()
    remote.state.update(intro_pending=False)
    remote.push()
    expect(button).to_have_text("Next song")
    expect(button).to_be_enabled()
    button.click()
    remote.wait_command("skip_next", key="current")
    remote.state.update(next_pending=True)
    remote.push()
    expect(button).to_be_disabled()
    remote.state.update(sections=None, next_pending=False)
    remote.push()
    expect(button).to_be_enabled()
    expect(button).to_have_text("Next song")
    expect(page.locator("#skip-section")).to_have_count(0)


def test_real_audio_gain_fades_and_cancels_without_altering_mix(page, remote_url):
    page.goto(remote_url)
    result = page.evaluate("""async () => {
      const {createSectionFade}=await import('/static/section-fade.js');
      const context=new OfflineAudioContext(1,88200,44100);
      let finished=0;
      const video=document.createElement("video");document.body.append(video);
      const fade=createSectionFade(context,context.destination,()=>finished++,video);
      const source=context.createConstantSource();source.connect(fade.gain);source.start();
      fade.run('intro');
      const rendered=await context.startRendering(), data=rendered.getChannelData(0);
      const samples=[data[0],data[33075],data[66150]];
      fade.reset();
      fade.run('next');
      await new Promise(resolve=>setTimeout(resolve,1600));
      const ended=finished, opacityAfterFade=getComputedStyle(video).opacity;
      fade.run('next');fade.reset();
      await new Promise(resolve=>setTimeout(resolve,1600));
      return {samples,ended,finished,gain:fade.gain.gain.value,opacityAfterFade,opacityAfterReset:getComputedStyle(video).opacity,animations:video.getAnimations().length};
    }""")
    assert result["samples"] == pytest.approx([1, .5, 0], abs=.02)
    assert result["ended"] == result["finished"] == 1
    assert float(result["opacityAfterFade"]) == 0
    assert float(result["opacityAfterReset"]) == 1
    assert result["animations"] == 0


def test_player_next_event_fades_then_reports_completion_once(remote, page, remote_url):
    import json
    remote.state["current"]["lyrics"] = []
    page.route_web_socket("**/ws?role=tv", remote.websocket)
    page.goto(remote_url.replace("/remote", "/tv"))
    page.locator("#enable-button").click()
    remote.wait_command("audio", value=True)
    # Ignoring the controls does not complete the song.
    page.wait_for_timeout(1700)
    assert not [m for m in remote.commands if m["action"] == "skip_complete"]
    remote.socket.send(json.dumps(dict(type="section_skip", key="stale", kind="next")))
    page.wait_for_timeout(1700)
    assert not [m for m in remote.commands if m["action"] == "skip_complete"]
    event = json.dumps(dict(type="section_skip", key="current", kind="next"))
    remote.socket.send(event)
    remote.socket.send(event)
    page.wait_for_function("document.querySelector('#backdrop').getAnimations().some(a=>a.effect.getKeyframes().some(f=>f.opacity==='0'))")
    opacity = page.locator("#backdrop").evaluate("""video => {
      const animation=video.getAnimations().find(a=>a.effect.getKeyframes().some(f=>f.opacity==='0'));
      animation.pause();animation.currentTime=750;
      const opacity=parseFloat(getComputedStyle(video).opacity);animation.play();return opacity;
    }""")
    assert opacity == pytest.approx(.5, abs=.02)
    remote.wait_command("skip_complete", key="current")
    assert len([m for m in remote.commands if m["action"] == "skip_complete"]) == 1


def test_intro_fades_out_seeks_while_black_then_fades_back_in(page, remote_url):
    page.goto(remote_url)
    result = page.evaluate("""async () => {
      const {createSectionFade}=await import('/static/section-fade.js');
      const context=new AudioContext();await context.resume();
      const video=document.createElement('video');document.body.append(video);
      let seekCount=0,blackAtSeek=null;
      const fade=createSectionFade(context,context.destination,()=>{},video);
      const sought=new Promise(resolve=>{
        fade.run('intro',()=>{
          seekCount++;blackAtSeek=Number(getComputedStyle(video).opacity);resolve();
        });
      });
      await new Promise(resolve=>setTimeout(resolve,500));
      const beforeSeek=seekCount, fadingOut=Number(getComputedStyle(video).opacity);
      await sought;
      const animation=video.getAnimations()[0];
      animation.pause();animation.currentTime=750;
      const fadingIn=Number(getComputedStyle(video).opacity);
      animation.play();
      await new Promise(resolve=>setTimeout(resolve,1600));
      const restored=Number(getComputedStyle(video).opacity);
      fade.run('intro',()=>seekCount++);fade.reset();
      await new Promise(resolve=>setTimeout(resolve,1600));
      const gainAfterReset=fade.gain.gain.value;
      await context.close();
      return {beforeSeek,fadingOut,blackAtSeek,fadingIn,restored,seekCount,gainAfterReset};
    }""")
    assert result["beforeSeek"] == 0
    assert 0 < result["fadingOut"] < 1
    assert result["blackAtSeek"] == 0
    assert result["fadingIn"] == pytest.approx(.5, abs=.02)
    assert result["restored"] == 1
    assert result["seekCount"] == 1
    assert result["gainAfterReset"] == 1


@pytest.mark.parametrize("theme", ["default", "classic"])
def test_section_countdown_and_responsive_icons(remote, page, remote_url, theme):
    import time
    now = time.time()
    remote.state.update(theme=theme, position=0, server_time=now,
                        transition_until=now+30, sections={"intro": 15, "outro": 94})
    page.goto(remote_url)
    if theme == "classic":
        page.locator('[data-tab="queue"]').click()
    button = page.get_by_role("button", name="Skip intro", exact=True)
    expect(button).to_be_disabled()
    remote.state.update(transition_until=0)
    remote.push()
    expect(button).to_be_enabled()
    for width, text_visible in ((320, False), (1440, True)):
        page.set_viewport_size({"width": width, "height": 900})
        selectors = ("#skip", "#hero-lyrics") if theme == "classic" else ("#skip", "#hero-lyrics", "#open-controls")
        for selector in selectors:
            control = page.locator(selector)
            expect(control.locator('svg')).to_be_visible()
            if text_visible:
                expect(control.locator('span')).to_be_visible()
            else:
                expect(control.locator('span')).to_be_hidden()
            box = control.bounding_box()
            assert box["x"] >= 0 and box["x"]+box["width"] <= width
