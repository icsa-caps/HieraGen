# $0$   CPU0
# $1$   CPU1

procedure Forbidden();
var R0: ClValue;
var R1: ClValue;
var R2: ClValue;

var match_cnt: 0..NrCaches;

begin
  /* Forbidden outcome */
  R0 := 0;
  R1 := 0;

  match_cnt := 0;

  /* Queue index position is important */
  if i_cpu[$0$].instrstr.Queue[1].cl = R0 then
    match_cnt := match_cnt + 1;
  endif;

  if i_cpu[$1$].instrstr.Queue[1].cl = R1 then
    match_cnt := match_cnt + 1;
  endif;

  if match_cnt = NrCaches then
    error "Litmus Test Failed"
  endif;

end;