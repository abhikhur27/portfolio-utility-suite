module tb;
 parameter MUTATION=0;
 logic clk=0,rst=1,in_valid=0,out_ready=0;logic[15:0] in_data=0;
 wire in_ready,out_valid;wire[15:0] out_data;
 integer seed,cycle,sent;string vcd;
 elastic_fifo #(.MUTATION(MUTATION)) dut(.*);
 always #5 clk=~clk;
 initial begin
  if(!$value$plusargs("seed=%d",seed))seed=7;
  if(!$value$plusargs("vcd=%s",vcd))vcd="build/trace.vcd";
  $dumpfile(vcd);$dumpvars(0,tb);
  repeat(3)@(negedge clk);rst=0;sent=0;
  for(cycle=0;cycle<512;cycle=cycle+1)begin
   @(negedge clk);
   in_valid=(sent<96);in_data=sent;
   out_ready=(cycle>=400)?1:(($random(seed)&7)>3);
   @(posedge clk);if(in_valid&&in_ready)sent=sent+1;
  end
  @(negedge clk);in_valid=0;out_ready=1;repeat(8)@(negedge clk);$finish;
 end
endmodule
